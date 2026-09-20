/* The whole control path, driven by synthetic crank edges.
 *
 * This is the closest thing to a running engine that exists without
 * hardware: teeth go in, coil and injector edges come out, and the
 * safety logic sits in between with the authority to stop both.
 */
#include <math.h>

#include "ecu.h"
#include "crank_sim.h"
#include "hal_host.h"
#include "tq_test.h"

#define TEETH 60
#define MISSING 2
#define DPT (360.0f / (f32)TEETH)

typedef struct {
    ecu_t ecu;
    dec_config_t cfg;
    f32 true_angle;
    tq_time_t t;
    f32 rpm;
    f32 fast_accum;
    f32 slow_accum;
} rig_t;

static void on_crank(tq_time_t t, bool rising, void *ctx)
{ (void)rising;
    ecu_on_crank_edge(&((rig_t *)ctx)->ecu, t);
}

static void on_cam(tq_time_t t, bool rising, void *ctx)
{
    ecu_on_cam_edge(&((rig_t *)ctx)->ecu, 0u, t, rising);
}

static void rig_init(rig_t *r, f32 rpm)
{
    hal_host_reset();
    ecu_init(&r->ecu);
    r->cfg = decoder_config_b48();
    r->true_angle = 0.0f;
    r->t = 1000000u;
    r->rpm = rpm;
    r->fast_accum = 0.0f;
    r->slow_accum = 0.0f;
    hal_crank_set_callback(on_crank, r);
    hal_cam_set_callback(HAL_CAP_CAM_1, on_cam, r);

    ecu_signals_t *s = &r->ecu.sig;
    s->ve = 0.90f;
    s->map_kpa = 95.0f;
    s->mbt_deg = 22.0f;
    s->knock_limit_deg = 30.0f;
    s->spark_deg = 20.0f;
    s->lambda_target = 1.0f;
    s->lambda_meas = 1.0f;
    s->rail_kpa = 8000.0f;
    s->pedal_a = s->pedal_b = 30.0f;
    s->tps_a = s->tps_b = s->tps_cmd = 30.0f;
    s->torque_request = 200.0f;
}

static void step_tooth(rig_t *r)
{
    f32 deg_per_us = r->rpm * 6.0f / 1.0e6f;
    u32 dt = (u32)(DPT / deg_per_us);
    f32 dt_s = (f32)dt * 1e-6f;
    r->t += dt;
    f32 before = r->true_angle;
    r->true_angle = tq_wrap_deg(r->true_angle + DPT);

    /* Emit every cam edge the crank just swept past, on both cams. */
    for (u8 cam = 0; cam < 2u; cam++) {
        const dec_cam_pattern_t *cp = &r->cfg.cam[cam];
        cam_sim_hit_t hit[DEC_MAX_CAM_EDGES];
        u8 nh = cam_sim_crossed(cp, before, r->true_angle, 0.0f,
                                hit, DEC_MAX_CAM_EDGES);
        for (u8 k = 0; k < nh; k++) {
            hal_host_cam_edge_ch((hal_cap_t)(HAL_CAP_CAM_1 + cam), r->t,
                                 cp->e[hit[k].idx].rising);
        }
    }

    f32 rel = r->true_angle;
    while (rel >= 360.0f) rel -= 360.0f;
    f32 from_gap = rel - r->cfg.gap_to_tdc_deg;
    while (from_gap < 0.0f) from_gap += 360.0f;
    int idx = (int)(from_gap / DPT + 0.5f);
    if (idx < TEETH - MISSING) {
        hal_host_crank_edge(r->t);
    } else {
        hal_host_advance_to(r->t);
    }

    /* the periodic tasks, at their real rates */
    r->fast_accum += dt_s;
    while (r->fast_accum >= 0.001f) {
        ecu_fast_task(&r->ecu, 0.001f);
        r->fast_accum -= 0.001f;
    }
    r->slow_accum += dt_s;
    while (r->slow_accum >= 0.010f) {
        ecu_slow_task(&r->ecu, 0.010f);
        ecu_diag_task(&r->ecu, 0.010f);
        r->slow_accum -= 0.010f;
    }
}

static void spin(rig_t *r, int teeth)
{
    for (int i = 0; i < teeth; i++) step_tooth(r);
}

static int count(hal_out_t ch, bool rising)
{
    int n = 0;
    for (u32 i = 0; i < hal_host_event_count; i++) {
        if (hal_host_events[i].ch == ch && hal_host_events[i].rising == rising) n++;
    }
    return n;
}

int main(void)
{
    rig_t r;

    TQ_CASE("a stopped engine fires nothing");
    rig_init(&r, 1000.0f);
    ecu_fast_task(&r.ecu, 0.001f);
    TQ_CHECK(r.ecu.sig.state == ECU_OFF, "state %d", r.ecu.sig.state);
    TQ_CHECK(count(HAL_OUT_COIL_1, true) == 0, "a coil charged with no engine");
    TQ_CHECK(count(HAL_OUT_INJ_1, true) == 0, "an injector opened with no engine");
    TQ_PASS("silent when stopped");

    TQ_CASE("cranking reaches sync and starts firing");
    rig_init(&r, 250.0f);
    spin(&r, 4 * TEETH);
    TQ_CHECK(decoder_has_phase(&r.ecu.dec), "no phase after four revolutions");
    hal_host_event_count = 0;
    spin(&r, 2 * TEETH);
    TQ_CHECK(count(HAL_OUT_COIL_1, false) >= 1, "no spark while cranking");
    TQ_CHECK(count(HAL_OUT_INJ_1, true) >= 1, "no injection while cranking");
    TQ_PASS("starts");

    TQ_CASE("runs cleanly at speed");
    rig_init(&r, 3000.0f);
    spin(&r, 4 * TEETH);
    hal_host_event_count = 0;
    spin(&r, 2 * TEETH);
    for (u8 c = 0; c < 4; c++) {
        TQ_CHECK(count((hal_out_t)(HAL_OUT_COIL_1 + c), false) == 1,
                 "cylinder %d fired %d times in one cycle", c + 1,
                 count((hal_out_t)(HAL_OUT_COIL_1 + c), false));
        TQ_CHECK(count((hal_out_t)(HAL_OUT_INJ_1 + c), true) == 1,
                 "cylinder %d injected %d times in one cycle", c + 1,
                 count((hal_out_t)(HAL_OUT_INJ_1 + c), true));
    }
    TQ_CHECK(r.ecu.sig.state == ECU_RUNNING, "state %d", r.ecu.sig.state);
    TQ_PASS("one spark and one injection per cylinder per cycle");

    TQ_CASE("the torque estimate is plausible");
    TQ_CHECK(r.ecu.sig.torque_estimate > 20.0f
             && r.ecu.sig.torque_estimate < 400.0f,
             "torque %.0f Nm", (double)r.ecu.sig.torque_estimate);
    TQ_CHECK(r.ecu.sig.pw_us > 500 && r.ecu.sig.pw_us < 20000,
             "pulse width %u us", r.ecu.sig.pw_us);
    TQ_CHECK(isfinite(r.ecu.sig.torque_authority), "authority is NaN");

    TQ_CASE("the knock limit is enforced, not advised");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        r.ecu.sig.knock_limit_deg = 8.0f;
        r.ecu.sig.spark_deg = 35.0f;          /* ask for far too much */
        ecu_fast_task(&r.ecu, 0.001f);
        TQ_NEAR(r.ecu.sig.spark_deg, 8.0f, 1e-3, "spark was not held at the limit");
        TQ_PASS("knock limit enforced");
    }

    TQ_CASE("retard is bounded by max_cut_retard");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        r.ecu.sig.spark_deg = -200.0f;
        ecu_fast_task(&r.ecu, 0.001f);
        TQ_CHECK(r.ecu.sig.spark_deg >= r.ecu.sig.mbt_deg - r.ecu.max_cut_retard - 1e-3f,
                 "spark %.1f is past the clamp", (double)r.ecu.sig.spark_deg);
        TQ_PASS("retard clamped");
    }

    TQ_CASE("the rev limiter cuts fuel");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        r.rpm = 7600.0f;
        spin(&r, 2 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        TQ_CHECK(r.ecu.fuel_cut, "no fuel cut past the limiter");
        TQ_CHECK(count(HAL_OUT_INJ_1, true) == 0, "still injecting past the limiter");
        TQ_PASS("limiter cuts fuel");
    }

    TQ_CASE("a cut never leaves a coil charged");
    {
        rig_init(&r, 4000.0f);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 11);
        r.ecu.sig.map_kpa = 400.0f;           /* overboost: hard cut */
        spin(&r, 3 * TEETH);
        int rise = 0, fall = 0;
        for (u8 c = 0; c < 4; c++) {
            rise += count((hal_out_t)(HAL_OUT_COIL_1 + c), true);
            fall += count((hal_out_t)(HAL_OUT_COIL_1 + c), false);
        }
        TQ_CHECK(rise == fall, "%d charged, %d fired", rise, fall);
        TQ_PASS("no coil stranded by a cut");
    }

    TQ_CASE("a pedal fault opens the throttle bridge");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        r.ecu.sig.pedal_a = 90.0f;
        r.ecu.sig.pedal_b = 5.0f;
        /* the debounce is 100 ms, so 150 one-millisecond cycles */
        for (int i = 0; i < 150; i++) ecu_fast_task(&r.ecu, 0.001f);
        TQ_CHECK(r.ecu.mon.limp >= MON_REDUCED, "no limp on a pedal fault");
        TQ_CHECK(r.ecu.mon.fault == MON_F_PEDAL_PLAUSIBILITY,
                 "fault reported as %d", r.ecu.mon.fault);
        TQ_CHECK(hal_host_throttle_enabled(),
                 "a reduced-power limp should not open the bridge outright");
        TQ_PASS("pedal fault handled");
    }

    TQ_CASE("a throttle fault opens the bridge so the spring can shut it");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        TQ_CHECK(hal_host_throttle_enabled(), "precondition");
        r.ecu.sig.tps_a = 90.0f;
        r.ecu.sig.tps_b = 5.0f;
        for (int i = 0; i < 150; i++) ecu_fast_task(&r.ecu, 0.001f);
        TQ_CHECK(r.ecu.mon.limp >= MON_IDLE_ONLY, "limp %d", r.ecu.mon.limp);
        TQ_CHECK(!hal_host_throttle_enabled(),
                 "the throttle is still being driven with a plausibility fault");
        TQ_PASS("bridge opened on a throttle fault");
    }

    TQ_CASE("losing the crank signal stops the engine firing");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 4 * TEETH);
        TQ_CHECK(decoder_has_phase(&r.ecu.dec), "precondition");
        hal_host_advance_to(r.t + 500000u);
        ecu_slow_task(&r.ecu, 0.01f);
        hal_host_event_count = 0;
        hal_host_advance_to(r.t + 1000000u);
        TQ_CHECK(!decoder_has_phase(&r.ecu.dec), "still claims phase");
        for (u8 c = 0; c < 4; c++) {
            TQ_CHECK(!hal_out_is_active((hal_out_t)(HAL_OUT_COIL_1 + c)),
                     "coil %d still live after signal loss", c + 1);
        }
        TQ_PASS("outputs dropped when the crank signal stops");
    }

    TQ_CASE("the watchdog is only kicked while the fast task advances");
    {
        rig_init(&r, 3000.0f);
        spin(&r, 2 * TEETH);
        u32 before = hal_host_watchdog_kicks();
        TQ_CHECK(before > 0, "the watchdog was never kicked while running");
        /* now stop calling the fast task and keep calling diag */
        for (int i = 0; i < 20; i++) ecu_diag_task(&r.ecu, 0.1f);
        u32 after = hal_host_watchdog_kicks();
        TQ_CHECK(after - before <= 1,
                 "the watchdog kept being kicked with the fast task stopped "
                 "(%u extra kicks)", after - before);
        TQ_PASS("watchdog reflects the fast task");
    }

    return tq_report("ecu");
}
