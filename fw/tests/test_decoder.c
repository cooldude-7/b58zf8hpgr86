/* Decoder tests against synthetic tooth streams.
 *
 * Every one of these is a condition a real engine produces: a cold crank
 * at 200 rpm, a hard pull to the limiter, a coil-induced noise spike on
 * the crank line, a lost tooth. A decoder that only works on a clean
 * constant-speed stream is a decoder that fails on the first start.
 */
#include <math.h>

#include "decoder.h"
#include "tq_test.h"

#define TEETH 60
#define MISSING 2
#define DEG_PER_TOOTH (360.0f / (f32)TEETH)

typedef struct {
    decoder_t dec;
    dec_config_t cfg;
    f32 true_angle;          /* 0..720 */
    tq_time_t t;
    f32 rpm;
    f32 cam_angle;
    int injected_noise;
} rig_t;

static void rig_init(rig_t *r, f32 rpm)
{
    r->cfg = decoder_config_b48();
    decoder_init(&r->dec, &r->cfg);
    r->true_angle = 0.0f;
    r->t = 1000000u;
    r->rpm = rpm;
    r->cam_angle = r->cfg.cam_edge_angle_deg;
    r->injected_noise = 0;
}

/* Advance the crank by one tooth width, firing whatever edges that
 * crosses. `accel` is in rpm per revolution. */
static void step_tooth(rig_t *r, f32 accel_rpm_per_rev)
{
    f32 deg = DEG_PER_TOOTH;
    f32 deg_per_us = r->rpm * 360.0f / 60.0f / 1.0e6f;
    u32 dt = (u32)(deg / deg_per_us);
    r->t += dt;

    f32 before = r->true_angle;
    r->true_angle = tq_wrap_deg(r->true_angle + deg);

    /* cam edge once per 720 */
    f32 c = r->cam_angle;
    int crossed = (before < c && r->true_angle >= c)
                  || (before > r->true_angle && (c > before || c <= r->true_angle));
    if (crossed) {
        decoder_on_cam_edge(&r->dec, r->t);
    }

    /* Is there a tooth here? The gap is the last `missing` positions of
     * each revolution, measured from gap_to_tdc. */
    f32 rel = r->true_angle;
    while (rel >= 360.0f) rel -= 360.0f;
    f32 from_gap = rel - r->cfg.gap_to_tdc_deg;
    while (from_gap < 0.0f) from_gap += 360.0f;
    int idx = (int)(from_gap / DEG_PER_TOOTH + 0.5f);
    int present = (idx < TEETH - MISSING);

    if (present) {
        decoder_on_crank_edge(&r->dec, r->t);
    }

    r->rpm += accel_rpm_per_rev * (deg / 360.0f);
    if (r->rpm < 50.0f) r->rpm = 50.0f;
}

static void spin(rig_t *r, int teeth, f32 accel)
{
    for (int i = 0; i < teeth; i++) {
        step_tooth(r, accel);
    }
}

int main(void)
{
    /* ---- sync acquisition ------------------------------------------- */
    TQ_CASE("starts with no idea where the engine is");
    rig_t r;
    rig_init(&r, 1000.0f);
    TQ_CHECK(r.dec.state == DEC_SEEKING, "state was %d", r.dec.state);
    TQ_CHECK(!decoder_has_phase(&r.dec), "claimed phase before any teeth");

    TQ_CASE("reaches full sync within three revolutions");
    spin(&r, 3 * TEETH, 0.0f);
    TQ_CHECK(r.dec.state == DEC_FULL_SYNC, "state was %d after 3 revs", r.dec.state);
    TQ_PASS("sync acquired");

    TQ_CASE("reports the right speed");
    TQ_NEAR(decoder_rpm(&r.dec), 1000.0f, 15.0f, "steady 1000 rpm");

    TQ_CASE("predicted angle tracks the real one");
    spin(&r, 120, 0.0f);
    f32 predicted = decoder_angle_at(&r.dec, r.t);
    TQ_NEAR(fabsf(tq_angle_diff(predicted, r.true_angle)), 0.0f, 1.0f,
            "predicted %.1f vs true %.1f", predicted, r.true_angle);

    TQ_CASE("predicts angle between teeth, not just at them");
    {
        f32 deg_per_us = r.rpm * 6.0f / 1.0e6f;
        u32 half = (u32)(DEG_PER_TOOTH * 0.5f / deg_per_us);
        f32 mid = decoder_angle_at(&r.dec, r.t + half);
        TQ_NEAR(fabsf(tq_angle_diff(mid, tq_wrap_deg(r.true_angle + 3.0f))), 0.0f,
                1.0f, "mid-tooth prediction %.1f", mid);
    }

    /* ---- scheduling ------------------------------------------------- */
    TQ_CASE("can say when a future angle arrives");
    {
        f32 target = tq_wrap_deg(r.true_angle + 90.0f);
        tq_time_t when = 0;
        bool ok = decoder_time_for_angle(&r.dec, r.t, target, &when);
        TQ_CHECK(ok, "refused to schedule 90 degrees ahead");
        f32 dt_us = (f32)(when - r.t);
        f32 expect = 90.0f / (r.rpm * 6.0f / 1.0e6f);
        TQ_NEAR(dt_us, expect, expect * 0.05f, "time to 90 deg");
    }

    TQ_CASE("an angle just behind us is scheduled for the next cycle");
    {
        f32 target = tq_wrap_deg(r.true_angle - 10.0f);
        tq_time_t when = 0;
        bool ok = decoder_time_for_angle(&r.dec, r.t, target, &when);
        TQ_CHECK(ok, "refused");
        TQ_CHECK(tq_after(when, r.t), "scheduled in the past");
        f32 dt_us = (f32)(when - r.t);
        f32 full = 710.0f / (r.rpm * 6.0f / 1.0e6f);
        TQ_NEAR(dt_us, full, full * 0.1f, "should be nearly a full cycle away");
    }

    /* ---- acceleration ------------------------------------------------ */
    TQ_CASE("tracks a hard pull without falling behind");
    {
        rig_t a;
        rig_init(&a, 2000.0f);
        spin(&a, 3 * TEETH, 0.0f);
        spin(&a, 4 * TEETH, 900.0f);          /* ~900 rpm per revolution */
        f32 p = decoder_angle_at(&a.dec, a.t);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "lost sync while accelerating");
        TQ_NEAR(fabsf(tq_angle_diff(p, a.true_angle)), 0.0f, 2.0f,
                "predicted %.1f vs true %.1f at %.0f rpm", p, a.true_angle, a.rpm);
        TQ_PASS("holds sync through acceleration");
    }

    TQ_CASE("tracks a hard decel");
    {
        rig_t a;
        rig_init(&a, 6000.0f);
        spin(&a, 3 * TEETH, 0.0f);
        spin(&a, 4 * TEETH, -900.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "lost sync while decelerating");
        f32 p = decoder_angle_at(&a.dec, a.t);
        TQ_NEAR(fabsf(tq_angle_diff(p, a.true_angle)), 0.0f, 2.0f,
                "predicted %.1f vs true %.1f", p, a.true_angle);
    }

    /* ---- cranking ----------------------------------------------------- */
    TQ_CASE("syncs at cranking speed");
    {
        rig_t a;
        rig_init(&a, 200.0f);
        spin(&a, 3 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "no sync at 200 rpm (state %d)",
                 a.dec.state);
        TQ_NEAR(decoder_rpm(&a.dec), 200.0f, 10.0f, "cranking speed");
        TQ_PASS("syncs while cranking");
    }

    TQ_CASE("survives the speed wobble of a real starter");
    {
        rig_t a;
        rig_init(&a, 180.0f);
        for (int i = 0; i < 5 * TEETH; i++) {
            /* a starter drags the engine unevenly, worst over compression */
            f32 wobble = (i % 30 < 15) ? -40.0f : 40.0f;
            step_tooth(&a, wobble);
        }
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "lost sync on an uneven crank");
    }

    /* ---- robustness --------------------------------------------------- */
    TQ_CASE("rejects a noise spike on the crank line");
    {
        rig_t a;
        rig_init(&a, 3000.0f);
        spin(&a, 3 * TEETH, 0.0f);
        u32 before_noise = a.dec.noise_count;
        /* a coil firing puts a spurious edge a few microseconds after a
         * real one -- far too early to be a tooth */
        decoder_on_crank_edge(&a.dec, a.t + 3u);
        TQ_CHECK(a.dec.noise_count > before_noise, "noise edge was accepted");
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "one noise edge broke sync");
        spin(&a, TEETH, 0.0f);
        f32 p = decoder_angle_at(&a.dec, a.t);
        TQ_NEAR(fabsf(tq_angle_diff(p, a.true_angle)), 0.0f, 2.0f,
                "angle after noise");
        TQ_PASS("noise rejected, sync kept");
    }

    TQ_CASE("loses sync when the teeth stop");
    {
        rig_t a;
        rig_init(&a, 1500.0f);
        spin(&a, 3 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "precondition");
        decoder_check_timeout(&a.dec, a.t + 500000u);      /* half a second */
        TQ_CHECK(a.dec.state == DEC_SEEKING, "kept sync with a stopped engine");
        TQ_CHECK(!decoder_has_phase(&a.dec), "still claims phase");
        TQ_PASS("sync dropped on stall");
    }

    TQ_CASE("does not time out between teeth at idle");
    {
        rig_t a;
        rig_init(&a, 700.0f);
        spin(&a, 3 * TEETH, 0.0f);
        decoder_check_timeout(&a.dec, a.t + 1000u);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "timed out mid-revolution");
    }

    TQ_CASE("recovers sync after a dropout");
    {
        rig_t a;
        rig_init(&a, 2500.0f);
        spin(&a, 3 * TEETH, 0.0f);
        decoder_check_timeout(&a.dec, a.t + 500000u);
        TQ_CHECK(a.dec.state == DEC_SEEKING, "precondition");
        /* Five revolutions: crank sync takes two, and the cam only speaks
         * once per cycle, so full phase can legitimately take two more. */
        spin(&a, 5 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "never re-synced (state %d)",
                 a.dec.state);
        TQ_PASS("re-syncs after a dropout");
    }

    TQ_CASE("timestamp wraparound does not break prediction");
    {
        rig_t a;
        rig_init(&a, 3000.0f);
        a.t = 0xFFFF0000u;                    /* about 65 ms before wrap */
        spin(&a, 4 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "lost sync across the wrap");
        f32 p = decoder_angle_at(&a.dec, a.t);
        TQ_NEAR(fabsf(tq_angle_diff(p, a.true_angle)), 0.0f, 2.0f,
                "angle across wrap: predicted %.1f true %.1f", p, a.true_angle);
        TQ_PASS("survives the 71-minute timer wrap");
    }

    TQ_CASE("angle is never reported without sync");
    {
        rig_t a;
        rig_init(&a, 1000.0f);
        tq_time_t when;
        TQ_CHECK(!decoder_time_for_angle(&a.dec, a.t, 100.0f, &when),
                 "scheduled an event with no sync");
    }

    return tq_report("decoder");
}
