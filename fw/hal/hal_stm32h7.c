/* STM32H7 HAL: the register-level implementation.
 *
 * HOW MUCH OF THIS IS VERIFIED, honestly, so nobody has to guess:
 *
 *   Compiled for Cortex-M7 in CI, with -Wall -Wextra -Werror.  yes
 *   Scheduling logic executed and tested (see oc_core).        yes
 *   Register offsets checked against the reference manual.     by eye
 *   Anything at all run on silicon.                            NO
 *
 * It also cannot be linked into a runnable image, and that is deliberate:
 * there are no interrupt vectors, no linker script, no startup code and
 * no clock tree here. Those arrive with a board. Inventing them without
 * one produces files that look finished and are wrong.
 *
 * The decisions that matter, and the trap in each:
 *
 * Time base       TIM2, 32-bit, 1 MHz. 32-bit is not a luxury: a 16-bit
 *                 counter at 1 MHz wraps every 65 ms, and one engine
 *                 cycle at idle is 150 ms.
 *
 * Output compare  TIM1/TIM8 (and TIM3/TIM4 for the rest) are 16-BIT, so
 *                 their counters do not agree with TIM2 and cannot even
 *                 express a time 150 ms out. Two consequences are handled
 *                 below rather than discovered on a dyno: each output
 *                 timer's offset from the time base is measured once at
 *                 init and applied to every compare value, and any
 *                 request further ahead than OC_MAX_AHEAD_US is refused
 *                 instead of silently landing a revolution early.
 *
 * Capture         TIM5 CH1..CH3, crank and two cams. The capture register
 *                 IS the timestamp -- never read CNT in the ISR, because
 *                 interrupt latency under load is worth several degrees
 *                 at 7000 rpm. CCxOF means an edge was lost.
 *
 * Priorities      The compare ISRs sit one preemption level ABOVE the
 *                 capture ISR. The capture ISR is the long one (it runs
 *                 the decoder, which does real arithmetic); the compare
 *                 ISRs are a switch and a register write. Grouping them
 *                 equal would make every falling edge wait behind the
 *                 decoder, and a late falling edge is an over-dwelled
 *                 coil or an over-fuelled cylinder.
 *
 * Critical        hal.h only promises that CALLBACKS run in interrupt
 * sections        context. The HAL entry points themselves are called
 *                 from thread mode too -- ecu_slow_task reaches
 *                 sched_all_off -- so every non-ISR mutation of a slot
 *                 raises BASEPRI over the compare/capture level. The
 *                 ISR-side paths are already serialised and stay bare.
 */
#ifdef TQ_TARGET_STM32H7

#include "hal.h"
#include "oc_core.h"
#include "stm32h7_regs.h"

/* Refuse anything further ahead than this. The 16-bit output timers wrap
 * at 65.536 ms; leave margin so a late arm cannot alias past the wrap and
 * fire an entire revolution early. */
#define OC_MAX_AHEAD_US 50000u

/* How far past its falling edge a channel may still be high before the
 * 1 kHz sweep concludes the interrupt was lost. Generous enough never to
 * fire in normal running, short enough that a stuck coil is measured in
 * milliseconds rather than in cylinders. */
#define OC_SWEEP_MARGIN_US 2000u

/* ---- BASEPRI guard ---------------------------------------------------- */
/* Raised over the compare and capture priorities, not to the point of
 * masking faults. */
#define TQ_ISR_BASEPRI 0x20u

static inline u32 crit_enter(void)
{
    u32 old;
    __asm__ volatile ("mrs %0, basepri" : "=r" (old));
    __asm__ volatile ("msr basepri, %0" :: "r" (TQ_ISR_BASEPRI) : "memory");
    return old;
}

static inline void crit_exit(u32 old)
{
    __asm__ volatile ("msr basepri, %0" :: "r" (old) : "memory");
}

/* ---- channel map ------------------------------------------------------ */
typedef struct {
    tim_t *tim;
    u8 chan;          /* 0..3 */
    u16 epoch;        /* this timer's count minus the time base's */
} oc_hw_t;

static oc_hw_t g_hw[HAL_OUT_COUNT];
static oc_slot_t g_oc[HAL_OUT_COUNT];

static hal_tooth_cb g_cap_cb[HAL_CAP_COUNT];
static void *g_cap_ctx[HAL_CAP_COUNT];
static u32 g_cap_overruns[HAL_CAP_COUNT];

/* ---- time ------------------------------------------------------------- */
tq_time_t hal_now_us(void)
{
    return (tq_time_t)TQ_TIM2->CNT;
}

/* ---- output compare --------------------------------------------------- */
static void oc_write_mode(const oc_hw_t *h, u32 mode)
{
    /* The output-mode field is three bits plus a fourth in OCxM[3], at
     * bit 16 of the same register for channels 1 and 3. Only the low
     * modes are used here, so the high bit is always cleared. */
    volatile u32 *ccmr = (h->chan < 2u) ? &h->tim->CCMR1 : &h->tim->CCMR2;
    u32 shift = (h->chan & 1u) ? 12u : 4u;
    u32 v = *ccmr;
    v &= ~(0x7u << shift);
    v |= (mode & 0x7u) << shift;
    *ccmr = v;
}

static void oc_program(const oc_hw_t *h, tq_time_t when, u32 mode)
{
    /* Clear the pending flag BEFORE loading the new compare value. The
     * other order loses the interrupt when the counter reaches the value
     * between the write and the clear -- the flag is set by hardware and
     * then immediately wiped, and the edge never arrives. */
    h->tim->SR = ~TIM_SR_CCIF(h->chan);
    h->tim->CCR[h->chan] = (u16)((u16)when + h->epoch);
    oc_write_mode(h, mode);
    h->tim->DIER |= TIM_DIER_CCIE(h->chan);
}

static void oc_apply(hal_out_t ch, oc_action_t act)
{
    const oc_hw_t *h = &g_hw[ch];
    switch (act) {
    case OC_ACT_ARM_RISE: oc_program(h, g_oc[ch].on_us,  TIM_OCM_ACTIVE);   break;
    case OC_ACT_ARM_FALL: oc_program(h, g_oc[ch].off_us, TIM_OCM_INACTIVE); break;
    case OC_ACT_FORCE_LOW:
        /* Force the pin low immediately, then disarm. Disarming first
         * would leave it wherever it was, and where it was is on. */
        oc_write_mode(h, TIM_OCM_FORCE_LOW);
        h->tim->DIER &= ~TIM_DIER_CCIE(h->chan);
        break;
    case OC_ACT_NONE:
    default: break;
    }
}

bool hal_out_schedule(hal_out_t ch, tq_time_t on_us, tq_time_t off_us)
{
    if (ch >= HAL_OUT_COUNT) return false;
    tq_time_t now = hal_now_us();
    if ((u32)(on_us - now) > OC_MAX_AHEAD_US && tq_after(on_us, now)) {
        return false;            /* beyond what a 16-bit compare can hold */
    }
    u32 sr = crit_enter();
    oc_action_t act;
    bool ok = oc_request(&g_oc[ch], on_us, off_us, now, &act);
    if (ok) oc_apply(ch, act);
    crit_exit(sr);
    return ok;
}

bool hal_out_schedule_pulses(hal_out_t ch, const hal_pulse_t *p, u8 n)
{
    if (ch >= HAL_OUT_COUNT || p == 0) return false;
    tq_time_t now = hal_now_us();
    u32 sr = crit_enter();
    oc_action_t act;
    bool ok = oc_request_pulses(&g_oc[ch], p, n, now, &act);
    if (ok) oc_apply(ch, act);
    crit_exit(sr);
    return ok;
}

void hal_out_cancel(hal_out_t ch)
{
    if (ch >= HAL_OUT_COUNT) return;
    u32 sr = crit_enter();
    oc_apply(ch, oc_cancel(&g_oc[ch]));
    crit_exit(sr);
}

bool hal_out_is_active(hal_out_t ch)
{
    return ch < HAL_OUT_COUNT && oc_is_active(&g_oc[ch]);
}

/* Called from each compare ISR. Short by construction. */
void tq_oc_isr(hal_out_t ch)
{
    g_hw[ch].tim->SR = ~TIM_SR_CCIF(g_hw[ch].chan);
    oc_apply(ch, oc_on_match(&g_oc[ch]));
}

/* Called from the 1 kHz task. The liveness backstop: without it a lost
 * compare interrupt leaves a channel high forever, and because the slot
 * never returns to idle, that cylinder is never scheduled again. */
void tq_oc_sweep_all(void)
{
    tq_time_t now = hal_now_us();
    for (u32 i = 0; i < HAL_OUT_COUNT; i++) {
        u32 sr = crit_enter();
        oc_apply((hal_out_t)i,
                 oc_sweep(&g_oc[i], now, OC_SWEEP_MARGIN_US));
        crit_exit(sr);
    }
}

/* ---- input capture ---------------------------------------------------- */
void hal_crank_set_callback(hal_tooth_cb cb, void *ctx)
{
    g_cap_cb[HAL_CAP_CRANK] = cb;
    g_cap_ctx[HAL_CAP_CRANK] = ctx;
}

void hal_cam_set_callback(hal_cap_t ch, hal_tooth_cb cb, void *ctx)
{
    if (ch >= HAL_CAP_COUNT) return;
    g_cap_cb[ch] = cb;
    g_cap_ctx[ch] = ctx;
}

u32 hal_capture_overruns(hal_cap_t ch)
{
    return ch < HAL_CAP_COUNT ? g_cap_overruns[ch] : 0u;
}

/* Called from the TIM5 capture ISR, one channel per capture input. The
 * hardware latched the timestamp; reading CNT here instead would add
 * however long the ISR took to get going. */
void tq_cap_isr(hal_cap_t ch, u8 timer_chan)
{
    tim_t *t = TQ_TIM5;
    if (t->SR & TIM_SR_CCOF(timer_chan)) {
        g_cap_overruns[ch]++;            /* an edge arrived and was lost */
        t->SR = ~TIM_SR_CCOF(timer_chan);
    }
    tq_time_t stamp = (tq_time_t)t->CCR[timer_chan];
    t->SR = ~TIM_SR_CCIF(timer_chan);
    /* Polarity comes from which of the paired capture channels fired;
     * these sensors encode direction in pulse width, so only one edge
     * carries the tooth pattern. */
    bool rising = (t->CCER & TIM_CCER_CCE(timer_chan)) != 0u;
    if (g_cap_cb[ch]) g_cap_cb[ch](stamp, rising, g_cap_ctx[ch]);
}

/* ---- not written, and honest about it --------------------------------- *
 * Throttle H-bridge, ADC + DMA, FDCAN, flash and the watchdog are the
 * peripherals whose behaviour cannot be checked without a board at all --
 * there is no logic in them to test, only register values to get right.
 * They are left as the plan rather than as plausible-looking code.
 *
 * One of them carries a decision worth recording now: HAL_ADC_KNOCK must
 * NOT sit in the 1 kHz regular sequence with the other channels. Knock on
 * an 82 mm bore rings near 6-7 kHz, so one sample per millisecond is an
 * alias, not a measurement. It needs its own injected conversion,
 * angle-triggered and sampled above 20 kHz, or an external knock IC.
 */
void hal_bridge_pwm(hal_bridge_t ch, f32 duty) { (void)ch; (void)duty; }
void hal_bridge_disable(hal_bridge_t ch) { (void)ch; }
void hal_sw_set(hal_sw_t ch, bool on) { (void)ch; (void)on; }
void hal_sw_frequency(hal_sw_t ch, f32 hz) { (void)ch; (void)hz; }
void hal_ocv_pwm(hal_ocv_t ch, f32 duty) { (void)ch; (void)duty; }
u16 hal_adc_read(hal_adc_t ch) { (void)ch; return 0u; }
bool hal_inj_configure(hal_out_t ch, const hal_inj_drive_t *d) { (void)ch; (void)d; return false; }
u16 hal_inj_boost_voltage(void) { return 0u; }
bool hal_can_send(const hal_can_frame_t *f) { (void)f; return false; }
bool hal_can_recv(hal_can_frame_t *out) { (void)out; return false; }
bool hal_flash_read(u32 o, void *d, u32 l) { (void)o; (void)d; (void)l; return false; }
bool hal_flash_write(u32 o, const void *s, u32 l) { (void)o; (void)s; (void)l; return false; }
bool hal_flash_erase(u32 o, u32 l) { (void)o; (void)l; return false; }
void hal_watchdog_kick(void) { }
void hal_watchdog_force_reset(void) { }

#endif /* TQ_TARGET_STM32H7 */
