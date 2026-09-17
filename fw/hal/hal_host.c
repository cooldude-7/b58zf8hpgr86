/* Host implementation of the HAL.
 *
 * Timers become a recorded event list, ADC channels become variables,
 * CAN becomes a queue. This is what lets the whole control path run and
 * be tested on a PC, and what the C model is cross-checked against the
 * Python reference through.
 *
 * It is a test double, not a simulator: it does not model hardware
 * behaviour, it records what the firmware asked hardware to do.
 */
#include "hal_host.h"

#include <string.h>

static tq_time_t g_now;
static hal_tooth_cb g_crank_cb, g_cam_cb;
static void *g_crank_ctx, *g_cam_ctx;
static u16 g_adc[HAL_ADC_COUNT];
static f32 g_throttle;
static bool g_throttle_enabled;
static u32 g_watchdog_kicks;
static bool g_watchdog_reset;

typedef struct {
    bool armed;
    bool active;
    tq_time_t on_us;
    tq_time_t off_us;
    /* queued pulses beyond the one currently armed */
    hal_pulse_t queue[HAL_MAX_PULSES];
    u8 queued;
    u8 next;
} out_state_t;

static hal_inj_drive_t g_inj[HAL_OUT_COUNT];
static u16 g_boost_v = 65;

static out_state_t g_out[HAL_OUT_COUNT];

hal_event_t hal_host_events[HAL_HOST_MAX_EVENTS];
u32 hal_host_event_count;

void hal_host_reset(void)
{
    memset(g_out, 0, sizeof(g_out));
    memset(g_inj, 0, sizeof(g_inj));
    g_boost_v = 65;
    memset(g_adc, 0, sizeof(g_adc));
    hal_host_event_count = 0;
    g_now = 1000000u;
    g_throttle = 0.0f;
    g_throttle_enabled = true;
    g_watchdog_kicks = 0;
    g_watchdog_reset = false;
}

static void record(hal_out_t ch, bool rising, tq_time_t t)
{
    if (hal_host_event_count >= HAL_HOST_MAX_EVENTS) {
        return;
    }
    hal_event_t *e = &hal_host_events[hal_host_event_count++];
    e->ch = ch;
    e->rising = rising;
    e->t = t;
}

void hal_host_advance_to(tq_time_t t)
{
    /* Fire every edge that falls in (now, t], in time order. */
    for (;;) {
        int next = -1;
        tq_time_t best = 0;
        bool rising = false;
        for (int c = 0; c < HAL_OUT_COUNT; c++) {
            out_state_t *o = &g_out[c];
            if (o->armed && !o->active
                && !tq_after(o->on_us, t) && tq_after(o->on_us, g_now)) {
                if (next < 0 || tq_after(best, o->on_us)) {
                    next = c; best = o->on_us; rising = true;
                }
            }
            if (o->active
                && !tq_after(o->off_us, t) && tq_after(o->off_us, g_now)) {
                if (next < 0 || tq_after(best, o->off_us)) {
                    next = c; best = o->off_us; rising = false;
                }
            }
        }
        if (next < 0) {
            break;
        }
        g_now = best;
        if (rising) {
            g_out[next].active = true;
            record((hal_out_t)next, true, best);
        } else {
            g_out[next].active = false;
            record((hal_out_t)next, false, best);
            out_state_t *o = &g_out[next];
            if (o->next < o->queued) {
                /* next pulse of the sequence */
                o->on_us = o->queue[o->next].on_us;
                o->off_us = o->queue[o->next].off_us;
                o->next++;
                o->armed = true;
            } else {
                o->armed = false;
                o->queued = 0;
                o->next = 0;
            }
        }
    }
    g_now = t;
}

void hal_host_set_adc(hal_adc_t ch, u16 counts) { g_adc[ch] = counts; }
f32 hal_host_throttle(void) { return g_throttle; }
bool hal_host_throttle_enabled(void) { return g_throttle_enabled; }
u32 hal_host_watchdog_kicks(void) { return g_watchdog_kicks; }
bool hal_host_watchdog_tripped(void) { return g_watchdog_reset; }

void hal_host_crank_edge(tq_time_t t)
{
    hal_host_advance_to(t);
    if (g_crank_cb) g_crank_cb(t, g_crank_ctx);
}

void hal_host_cam_edge(tq_time_t t)
{
    hal_host_advance_to(t);
    if (g_cam_cb) g_cam_cb(t, g_cam_ctx);
}

/* ---- the HAL interface proper ---------------------------------------- */
tq_time_t hal_now_us(void) { return g_now; }

void hal_crank_set_callback(hal_tooth_cb cb, void *ctx)
{
    g_crank_cb = cb; g_crank_ctx = ctx;
}

void hal_cam_set_callback(hal_tooth_cb cb, void *ctx)
{
    g_cam_cb = cb; g_cam_ctx = ctx;
}

bool hal_out_schedule(hal_out_t ch, tq_time_t on_us, tq_time_t off_us)
{
    if (ch >= HAL_OUT_COUNT) {
        return false;
    }
    out_state_t *o = &g_out[ch];
    if (o->active) {
        /* already high: only the falling edge may move */
        o->off_us = off_us;
        return true;
    }
    if (!tq_after(on_us, g_now)) {
        return false;                /* the rising edge is already past */
    }
    o->armed = true;
    o->on_us = on_us;
    o->off_us = off_us;
    return true;
}

bool hal_out_schedule_pulses(hal_out_t ch, const hal_pulse_t *p, u8 n)
{
    if (ch >= HAL_OUT_COUNT || n == 0 || n > HAL_MAX_PULSES) {
        return false;
    }
    out_state_t *o = &g_out[ch];
    if (o->active) {
        return false;                /* mid-pulse: do not rewrite a sequence */
    }
    for (u8 i = 0; i < n; i++) {
        if (!tq_after(p[i].off_us, p[i].on_us)) {
            return false;            /* zero or negative width */
        }
        if (i && !tq_after(p[i].on_us, p[i - 1].off_us)) {
            return false;            /* overlapping or out of order */
        }
        /* the boost rail has to refill between pulses */
        if (i && (u32)(p[i].on_us - p[i - 1].off_us) < g_inj[ch].recharge_us) {
            return false;
        }
    }
    if (!tq_after(p[0].on_us, g_now)) {
        return false;
    }
    o->on_us = p[0].on_us;
    o->off_us = p[0].off_us;
    o->armed = true;
    o->queued = n;
    o->next = 1;
    for (u8 i = 0; i < n; i++) {
        o->queue[i] = p[i];
    }
    return true;
}

bool hal_inj_configure(hal_out_t ch, const hal_inj_drive_t *d)
{
    if (ch >= HAL_OUT_COUNT || d == 0) {
        return false;
    }
    if (d->peak_ma <= d->hold_ma || d->peak_us == 0 || d->boost_v == 0) {
        return false;                /* not a peak-and-hold profile */
    }
    g_inj[ch] = *d;
    return true;
}

u16 hal_inj_boost_voltage(void) { return g_boost_v; }

void hal_host_set_boost_voltage(u16 v) { g_boost_v = v; }

const hal_inj_drive_t *hal_host_inj_drive(hal_out_t ch)
{
    return ch < HAL_OUT_COUNT ? &g_inj[ch] : 0;
}

void hal_out_cancel(hal_out_t ch)
{
    if (ch < HAL_OUT_COUNT) {
        g_out[ch].armed = false;
        g_out[ch].active = false;
        g_out[ch].queued = 0;
        g_out[ch].next = 0;
    }
}

bool hal_out_is_active(hal_out_t ch)
{
    return ch < HAL_OUT_COUNT && g_out[ch].active;
}

void hal_throttle_pwm(f32 duty) { g_throttle = tq_clampf(duty, -1.0f, 1.0f); }
void hal_throttle_disable(void) { g_throttle_enabled = false; g_throttle = 0.0f; }

u16 hal_adc_read(hal_adc_t ch) { return ch < HAL_ADC_COUNT ? g_adc[ch] : 0; }

bool hal_can_send(const hal_can_frame_t *f) { (void)f; return true; }
bool hal_can_recv(hal_can_frame_t *out) { (void)out; return false; }

static u8 g_flash[65536];
bool hal_flash_read(u32 off, void *dst, u32 len)
{
    if (off + len > sizeof(g_flash)) return false;
    memcpy(dst, g_flash + off, len);
    return true;
}
bool hal_flash_write(u32 off, const void *src, u32 len)
{
    if (off + len > sizeof(g_flash)) return false;
    memcpy(g_flash + off, src, len);
    return true;
}
bool hal_flash_erase(u32 off, u32 len)
{
    if (off + len > sizeof(g_flash)) return false;
    memset(g_flash + off, 0xFF, len);
    return true;
}

void hal_watchdog_kick(void) { g_watchdog_kicks++; }
void hal_watchdog_force_reset(void) { g_watchdog_reset = true; }
