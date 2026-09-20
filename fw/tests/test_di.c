/* Direct injection: multi-pulse, injector drive, and the pump valve.
 *
 * These are the parts that make a direct injection engine different
 * from a port injected one. Each test below corresponds to a way the
 * fuelling can be quietly wrong on a real engine rather than obviously
 * broken on a bench.
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
    f32 fast_accum, slow_accum;
} rig_t;

static void on_crank(tq_time_t t, bool rising, void *ctx) { (void)rising; ecu_on_crank_edge(&((rig_t *)ctx)->ecu, t); }
static void on_cam(tq_time_t t, bool rising, void *ctx) { ecu_on_cam_edge(&((rig_t *)ctx)->ecu, 0u, t, rising); }

static void rig_init(rig_t *r, f32 rpm)
{
    hal_host_reset();
    ecu_init(&r->ecu);
    r->cfg = decoder_config_b48();
    r->true_angle = 0.0f;
    r->t = 1000000u;
    r->rpm = rpm;
    r->fast_accum = r->slow_accum = 0.0f;
    hal_crank_set_callback(on_crank, r);
    hal_cam_set_callback(HAL_CAP_CAM_1, on_cam, r);
    ecu_signals_t *s = &r->ecu.sig;
    s->ve = 0.90f; s->map_kpa = 95.0f;
    s->mbt_deg = 22.0f; s->knock_limit_deg = 30.0f; s->spark_deg = 20.0f;
    s->lambda_target = 1.0f; s->lambda_meas = 1.0f;
    s->rail_kpa = 8000.0f; s->rail_target_kpa = 8000.0f;
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
    if (idx < TEETH - MISSING) hal_host_crank_edge(r->t);
    else hal_host_advance_to(r->t);

    r->fast_accum += dt_s;
    while (r->fast_accum >= 0.001f) { ecu_fast_task(&r->ecu, 0.001f); r->fast_accum -= 0.001f; }
    r->slow_accum += dt_s;
    while (r->slow_accum >= 0.010f) {
        ecu_slow_task(&r->ecu, 0.010f); ecu_diag_task(&r->ecu, 0.010f);
        r->slow_accum -= 0.010f;
    }
}

static void spin(rig_t *r, int teeth) { for (int i = 0; i < teeth; i++) step_tooth(r); }

static int count(hal_out_t ch, bool rising)
{
    int n = 0;
    for (u32 i = 0; i < hal_host_event_count; i++)
        if (hal_host_events[i].ch == ch && hal_host_events[i].rising == rising) n++;
    return n;
}

int main(void)
{
    rig_t r;

    /* ---- injector drive profile -------------------------------------- */
    TQ_CASE("injectors are configured with a peak and hold profile");
    rig_init(&r, 2000.0f);
    {
        const hal_inj_drive_t *d = hal_host_inj_drive(HAL_OUT_INJ_1);
        TQ_CHECK(d->peak_ma > d->hold_ma, "peak %u is not above hold %u",
                 d->peak_ma, d->hold_ma);
        TQ_CHECK(d->boost_v > 40, "boost supply is only %u V", d->boost_v);
        TQ_CHECK(d->recharge_us > 0, "no recharge time: multi-pulse will misfire");
        TQ_PASS("peak and hold configured");
    }

    TQ_CASE("a profile that is not peak-and-hold is refused");
    {
        hal_inj_drive_t bad = { 65, 3000, 400, 3500, 300 };   /* hold above peak */
        TQ_CHECK(!hal_inj_configure(HAL_OUT_INJ_1, &bad), "accepted hold > peak");
        hal_inj_drive_t no_boost = { 0, 12000, 400, 3500, 300 };
        TQ_CHECK(!hal_inj_configure(HAL_OUT_INJ_1, &no_boost), "accepted no boost rail");
        TQ_PASS("bad profiles refused");
    }

    TQ_CASE("a sagging boost rail is reported");
    {
        rig_init(&r, 2000.0f);
        spin(&r, 4 * TEETH);
        TQ_CHECK(!r.ecu.sig.boost_low, "flagged low with a healthy rail");
        hal_host_set_boost_voltage(20);
        ecu_fast_task(&r.ecu, 0.001f);
        TQ_CHECK(r.ecu.sig.boost_low,
                 "a collapsed injector supply was not noticed");
        TQ_PASS("boost rail monitored");
    }

    /* ---- multi-pulse --------------------------------------------------- */
    TQ_CASE("a split injection produces two pulses per cylinder per cycle");
    {
        rig_init(&r, 3000.0f);
        r.ecu.sig.n_pulses = 2;
        r.ecu.sig.split_first = 0.35f;
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);                    /* one cycle */
        int opens = count(HAL_OUT_INJ_1, true);
        TQ_CHECK(opens == 2, "cylinder 1 opened %d times in one cycle", opens);
        TQ_PASS("two pulses delivered");
    }

    TQ_CASE("the split honours the requested ratio");
    {
        rig_init(&r, 3000.0f);
        r.ecu.sig.n_pulses = 2;
        r.ecu.sig.split_first = 0.30f;
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        /* measure the two pulse widths on cylinder 1 */
        f32 w[2] = { 0, 0 };
        int found = 0;
        tq_time_t rise = 0; bool have = false;
        for (u32 i = 0; i < hal_host_event_count && found < 2; i++) {
            hal_event_t *e = &hal_host_events[i];
            if (e->ch != HAL_OUT_INJ_1) continue;
            if (e->rising) { rise = e->t; have = true; }
            else if (have) { w[found++] = (f32)(e->t - rise); have = false; }
        }
        TQ_CHECK(found == 2, "only found %d complete pulses", found);
        if (found == 2) {
            f32 frac = w[0] / (w[0] + w[1]);
            TQ_NEAR(frac, 0.30f, 0.02f, "first pulse was %.0f%% of the charge",
                    (double)(frac * 100.0f));
            TQ_PASS("split ratio honoured");
        }
    }

    TQ_CASE("the pilot pulse comes before the main one");
    {
        rig_init(&r, 3000.0f);
        r.ecu.sig.n_pulses = 2;
        r.ecu.sig.split_first = 0.35f;
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        tq_time_t first = 0; bool got = false;
        int n = 0;
        for (u32 i = 0; i < hal_host_event_count; i++) {
            hal_event_t *e = &hal_host_events[i];
            if (e->ch != HAL_OUT_INJ_1 || !e->rising) continue;
            if (!got) { first = e->t; got = true; }
            else { TQ_CHECK(tq_after(e->t, first), "second pulse is not later"); }
            n++;
        }
        TQ_CHECK(n == 2, "expected two openings, saw %d", n);
        TQ_PASS("pulse order correct");
    }

    TQ_CASE("pulses out of order are refused outright");
    {
        sched_t s;
        sched_init(&s, 4);
        sched_pulse_t p[2] = { { 200.0f, 2000 }, { 300.0f, 2000 } };  /* backwards */
        TQ_CHECK(!sched_set_pulses(&s, 0, p, 2), "accepted a reversed pattern");
        TQ_CHECK(s.rejected_patterns == 1, "the rejection was not counted");
        TQ_PASS("order enforced");
    }

    TQ_CASE("pulses too close for the boost supply are refused by the hardware");
    {
        hal_host_reset();
        hal_inj_drive_t d = { 65, 12000, 400, 3500, 500 };   /* 500 us recharge */
        hal_inj_configure(HAL_OUT_INJ_1, &d);
        tq_time_t now = hal_now_us();
        hal_pulse_t p[2];
        p[0].on_us = now + 1000; p[0].off_us = now + 2000;
        p[1].on_us = now + 2100; p[1].off_us = now + 3000;   /* only 100 us gap */
        TQ_CHECK(!hal_out_schedule_pulses(HAL_OUT_INJ_1, p, 2),
                 "accepted a second pulse before the supply could recover");
        p[1].on_us = now + 2600; p[1].off_us = now + 3400;   /* 600 us gap */
        TQ_CHECK(hal_out_schedule_pulses(HAL_OUT_INJ_1, p, 2),
                 "refused a properly spaced pair");
        TQ_PASS("recharge time enforced");
    }

    TQ_CASE("overlapping pulses are refused");
    {
        hal_host_reset();
        hal_inj_drive_t d = { 65, 12000, 400, 3500, 0 };
        hal_inj_configure(HAL_OUT_INJ_1, &d);
        tq_time_t now = hal_now_us();
        hal_pulse_t p[2];
        p[0].on_us = now + 1000; p[0].off_us = now + 3000;
        p[1].on_us = now + 2000; p[1].off_us = now + 4000;
        TQ_CHECK(!hal_out_schedule_pulses(HAL_OUT_INJ_1, p, 2), "accepted an overlap");
        TQ_PASS("overlap refused");
    }

    TQ_CASE("a fuel cut stops every pulse of a split pattern");
    {
        rig_init(&r, 3000.0f);
        r.ecu.sig.n_pulses = 2;
        r.ecu.sig.split_first = 0.35f;
        spin(&r, 4 * TEETH);
        r.rpm = 7600.0f;                       /* over the limiter */
        spin(&r, 2 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        TQ_CHECK(count(HAL_OUT_INJ_1, true) == 0,
                 "still injecting past the limiter");
        TQ_PASS("split pattern cut cleanly");
    }

    /* ---- the high pressure pump ---------------------------------------- */
    TQ_CASE("the pump valve is actually driven");
    {
        rig_init(&r, 2500.0f);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 4 * TEETH);
        int n = count(HAL_OUT_HPFP_MSV, true);
        TQ_CHECK(n > 0, "the metering valve never fired in two cycles");
        TQ_CHECK(r.ecu.sig.msv_events > 0, "no pump events counted");
        TQ_PASS("pump valve driven");
    }

    TQ_CASE("the valve closes later when less fuel is wanted");
    {
        tq_hpfp_sched_t cfg = tq_hpfp_sched_default();
        f32 full = 0.0f, part = 0.0f;
        TQ_CHECK(tq_hpfp_close_angle(&cfg, 1.0f, 0.0f, &full), "no angle at full duty");
        TQ_CHECK(tq_hpfp_close_angle(&cfg, 0.25f, 0.0f, &part), "no angle at part duty");
        TQ_CHECK(part > full,
                 "less delivery should close later in the stroke (%.1f vs %.1f)",
                 (double)part, (double)full);
        TQ_PASS("duty maps to close angle");
    }

    TQ_CASE("a duty of nothing does not pump");
    {
        tq_hpfp_sched_t cfg = tq_hpfp_sched_default();
        f32 a;
        TQ_CHECK(!tq_hpfp_close_angle(&cfg, 0.0f, 0.0f, &a),
                 "scheduled a stroke with no demand");
        TQ_PASS("no stroke at zero duty");
    }

    TQ_CASE("the pump does not run without phase");
    {
        rig_init(&r, 2500.0f);
        spin(&r, 4 * TEETH);
        hal_host_advance_to(r.t + 500000u);
        ecu_slow_task(&r.ecu, 0.01f);
        hal_host_event_count = 0;
        ecu_schedule_pump(&r.ecu, hal_now_us());
        TQ_CHECK(count(HAL_OUT_HPFP_MSV, true) == 0,
                 "pumped against an unknown engine position");
        TQ_PASS("pump needs phase");
    }

    TQ_CASE("the rail target reaches the pump loop");
    {
        rig_init(&r, 2500.0f);
        r.ecu.sig.rail_target_kpa = 15000.0f;
        spin(&r, 4 * TEETH);
        TQ_NEAR(r.ecu.hpfp.target_kpa, 15000.0f, 1.0f, "target not applied");
        TQ_CHECK(r.ecu.hpfp.duty > 0.0f,
                 "the loop is not demanding fuel with the rail far below target");
        TQ_PASS("rail target honoured");
    }

    return tq_report("direct injection");
}
