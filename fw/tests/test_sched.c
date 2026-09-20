/* Scheduler tests: does a requested angle become an edge at the right
 * time, and are the late-change rules obeyed?
 *
 * The rule that matters most: a coil that has started charging must
 * still fire. Every other rule here exists to keep that one true.
 */
#include <math.h>

#include "decoder.h"
#include "crank_sim.h"
#include "hal_host.h"
#include "sched.h"
#include "tq_test.h"

#define TEETH 60
#define MISSING 2
#define DPT (360.0f / (f32)TEETH)

typedef struct {
    decoder_t dec;
    dec_config_t cfg;
    sched_t sch;
    f32 true_angle;
    tq_time_t t;
    f32 rpm;
} rig_t;

static void on_crank(tq_time_t t, bool rising, void *ctx)
{ (void)rising;
    rig_t *r = (rig_t *)ctx;
    decoder_on_crank_edge(&r->dec, t);
    sched_update(&r->sch, &r->dec, t);
}

static void on_cam(tq_time_t t, bool rising, void *ctx)
{
    rig_t *r = (rig_t *)ctx;
    decoder_on_cam_edge(&r->dec, 0u, t, rising);
}

static void rig_init(rig_t *r, f32 rpm, u8 n_cyl)
{
    hal_host_reset();
    r->cfg = decoder_config_b48();
    decoder_init(&r->dec, &r->cfg);
    sched_init(&r->sch, n_cyl);
    /* inline four, firing order 1-3-4-2 */
    sched_set_tdc(&r->sch, 0, 0.0f);
    sched_set_tdc(&r->sch, 1, 180.0f);
    sched_set_tdc(&r->sch, 2, 360.0f);
    sched_set_tdc(&r->sch, 3, 540.0f);
    r->true_angle = 0.0f;
    r->t = 1000000u;
    r->rpm = rpm;
    hal_crank_set_callback(on_crank, r);
    hal_cam_set_callback(HAL_CAP_CAM_1, on_cam, r);
}

static void step_tooth(rig_t *r)
{
    f32 deg_per_us = r->rpm * 6.0f / 1.0e6f;
    u32 dt = (u32)(DPT / deg_per_us);
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
}

static void spin(rig_t *r, int teeth)
{
    for (int i = 0; i < teeth; i++) step_tooth(r);
}

static int count_events(hal_out_t ch, bool rising)
{
    int n = 0;
    for (u32 i = 0; i < hal_host_event_count; i++) {
        if (hal_host_events[i].ch == ch && hal_host_events[i].rising == rising) n++;
    }
    return n;
}

static tq_time_t last_event(hal_out_t ch, bool rising, bool *found)
{
    tq_time_t t = 0;
    *found = false;
    for (u32 i = 0; i < hal_host_event_count; i++) {
        if (hal_host_events[i].ch == ch && hal_host_events[i].rising == rising) {
            t = hal_host_events[i].t;
            *found = true;
        }
    }
    return t;
}

int main(void)
{
    rig_t r;

    /* ---- nothing fires without phase -------------------------------- */
    TQ_CASE("no spark before the engine is synced");
    rig_init(&r, 1000.0f, 4);
    sched_set_spark(&r.sch, 0, 20.0f, 2500);
    spin(&r, 40);                       /* not yet a full sync */
    TQ_CHECK(count_events(HAL_OUT_COIL_1, false) == 0,
             "fired %d times with no phase", count_events(HAL_OUT_COIL_1, false));
    TQ_PASS("silent until synced");

    /* ---- spark lands at the requested angle -------------------------- */
    TQ_CASE("spark fires at the requested advance");
    rig_init(&r, 3000.0f, 4);
    for (u8 c = 0; c < 4; c++) {
        sched_set_spark(&r.sch, c, 20.0f, 2000);
    }
    spin(&r, 4 * TEETH);
    hal_host_event_count = 0;           /* forget the acquisition transient */
    spin(&r, 2 * TEETH);

    int fires = count_events(HAL_OUT_COIL_1, false);
    TQ_CHECK(fires >= 1, "cylinder 1 fired %d times in two revolutions", fires);

    {
        bool found;
        tq_time_t fire_t = last_event(HAL_OUT_COIL_1, false, &found);
        TQ_CHECK(found, "no falling edge on coil 1");
        f32 at = decoder_angle_at(&r.dec, fire_t);
        /* cylinder 1 TDC is 0, so 20 BTDC is 700 in the 720 frame */
        f32 err = fabsf(tq_angle_diff(at, 700.0f));
        TQ_NEAR(err, 0.0f, 2.0f, "fired at %.1f, wanted 700", at);
        TQ_PASS("spark angle accurate to 2 degrees");
    }

    TQ_CASE("changing the advance moves the spark");
    {
        rig_init(&r, 3000.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 10.0f, 2000);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        bool f1; tq_time_t t1 = last_event(HAL_OUT_COIL_1, false, &f1);
        f32 a1 = decoder_angle_at(&r.dec, t1);

        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 30.0f, 2000);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        bool f2; tq_time_t t2 = last_event(HAL_OUT_COIL_1, false, &f2);
        f32 a2 = decoder_angle_at(&r.dec, t2);

        TQ_CHECK(f1 && f2, "missing spark events");
        f32 moved = tq_angle_diff(a2, a1);
        TQ_NEAR(moved, -20.0f, 3.0f, "advance 10 -> 30 should move spark 20 earlier");
        TQ_PASS("advance changes take effect");
    }

    /* ---- dwell ------------------------------------------------------- */
    TQ_CASE("dwell lasts as long as it was asked to");
    {
        rig_init(&r, 2000.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 20.0f, 3000);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        /* find a rising/falling pair on coil 1 */
        tq_time_t rise = 0; bool have_rise = false;
        for (u32 i = 0; i < hal_host_event_count; i++) {
            hal_event_t *e = &hal_host_events[i];
            if (e->ch != HAL_OUT_COIL_1) continue;
            if (e->rising) { rise = e->t; have_rise = true; }
            else if (have_rise) {
                TQ_NEAR((f32)(e->t - rise), 3000.0f, 60.0f, "dwell length");
                have_rise = false;
            }
        }
        TQ_PASS("dwell honoured");
    }

    TQ_CASE("dwell is clamped to the coil's limits");
    {
        rig_init(&r, 2000.0f, 4);
        sched_set_spark(&r.sch, 0, 20.0f, 100000);     /* absurd */
        TQ_CHECK(r.sch.cyl[0].dwell_us <= r.sch.max_dwell_us, "dwell not clamped");
        sched_set_spark(&r.sch, 0, 20.0f, 1);
        TQ_CHECK(r.sch.cyl[0].dwell_us >= r.sch.min_dwell_us, "dwell under minimum");
    }

    /* ---- firing order ------------------------------------------------ */
    TQ_CASE("every cylinder fires once per cycle");
    {
        rig_init(&r, 3000.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 20.0f, 2000);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);                 /* exactly one cycle */
        for (u8 c = 0; c < 4; c++) {
            int n = count_events((hal_out_t)(HAL_OUT_COIL_1 + c), false);
            TQ_CHECK(n == 1, "cylinder %d fired %d times in one cycle", c + 1, n);
        }
        TQ_PASS("one spark per cylinder per cycle");
    }

    /* ---- injection --------------------------------------------------- */
    TQ_CASE("injector opens for the requested pulse width");
    {
        rig_init(&r, 2500.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_injection(&r.sch, c, 300.0f, 4000);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 2 * TEETH);
        tq_time_t rise = 0; bool have = false; int checked = 0;
        for (u32 i = 0; i < hal_host_event_count; i++) {
            hal_event_t *e = &hal_host_events[i];
            if (e->ch != HAL_OUT_INJ_1) continue;
            if (e->rising) { rise = e->t; have = true; }
            else if (have) {
                TQ_NEAR((f32)(e->t - rise), 4000.0f, 60.0f, "pulse width");
                have = false; checked++;
            }
        }
        TQ_CHECK(checked >= 1, "no complete injection pulse");
        TQ_PASS("pulse width honoured");
    }

    /* ---- cuts -------------------------------------------------------- */
    TQ_CASE("a fuel cut stops injection within a cycle");
    {
        rig_init(&r, 3000.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_injection(&r.sch, c, 300.0f, 3000);
        spin(&r, 4 * TEETH);
        sched_enable_fuel(&r.sch, false);
        hal_host_event_count = 0;
        spin(&r, 4 * TEETH);
        int n = count_events(HAL_OUT_INJ_1, true);
        TQ_CHECK(n == 0, "injector opened %d times after a fuel cut", n);
        TQ_PASS("fuel cut respected");
    }

    TQ_CASE("a charging coil is always allowed to fire");
    {
        /* The failure this prevents: cutting spark mid-dwell leaves a
         * charged coil with nowhere to go, and the next thing it does is
         * fire at an angle nobody chose. */
        rig_init(&r, 3000.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 20.0f, 2500);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        /* cut spark at an arbitrary moment part way through a cycle */
        spin(&r, 7);
        sched_enable_spark(&r.sch, false);
        spin(&r, 3 * TEETH);
        int rising = 0, falling = 0;
        for (u8 c = 0; c < 4; c++) {
            rising += count_events((hal_out_t)(HAL_OUT_COIL_1 + c), true);
            falling += count_events((hal_out_t)(HAL_OUT_COIL_1 + c), false);
        }
        TQ_CHECK(rising == falling,
                 "%d coils charged but %d fired: a coil was left charged",
                 rising, falling);
        TQ_PASS("no coil left charged by a cut");
    }

    TQ_CASE("losing sync drops everything immediately");
    {
        rig_init(&r, 3000.0f, 4);
        for (u8 c = 0; c < 4; c++) {
            sched_set_spark(&r.sch, c, 20.0f, 2500);
            sched_set_injection(&r.sch, c, 300.0f, 3000);
        }
        spin(&r, 4 * TEETH);
        decoder_check_timeout(&r.dec, r.t + 500000u);
        sched_update(&r.sch, &r.dec, r.t + 500000u);
        for (u8 c = 0; c < 4; c++) {
            TQ_CHECK(!hal_out_is_active((hal_out_t)(HAL_OUT_COIL_1 + c)),
                     "coil %d still active after sync loss", c + 1);
            TQ_CHECK(!r.sch.cyl[c].spark_armed, "cylinder %d still armed", c + 1);
        }
        TQ_PASS("outputs dropped on sync loss");
    }

    /* ---- high rpm ----------------------------------------------------- */
    TQ_CASE("keeps up at the rev limiter");
    {
        rig_init(&r, 7200.0f, 4);
        for (u8 c = 0; c < 4; c++) sched_set_spark(&r.sch, c, 25.0f, 2000);
        spin(&r, 4 * TEETH);
        hal_host_event_count = 0;
        spin(&r, 4 * TEETH);
        for (u8 c = 0; c < 4; c++) {
            int n = count_events((hal_out_t)(HAL_OUT_COIL_1 + c), false);
            TQ_CHECK(n == 2, "cylinder %d fired %d times in two cycles at 7200 rpm",
                     c + 1, n);
        }
        TQ_CHECK(r.sch.missed_events == 0, "%u events were late at 7200 rpm",
                 r.sch.missed_events);
        TQ_PASS("keeps up at 7200 rpm");
    }

    return tq_report("scheduler");
}
