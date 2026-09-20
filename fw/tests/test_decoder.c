/* Decoder tests against synthetic tooth streams.
 *
 * Every one of these is a condition a real engine produces: a cold crank
 * at 200 rpm, a hard pull to the limiter, a coil-induced noise spike on
 * the crank line, a lost tooth. A decoder that only works on a clean
 * constant-speed stream is a decoder that fails on the first start.
 */
#include <math.h>

#include "crank_sim.h"
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
    f32 cam_adv[2];          /* cam advance, CRANK degrees, per cam */
    f32 cam_slew[2];         /* crank deg/s the phaser is moving */
    int drop_cam_edges;      /* swallow this many cam edges, then stop */
    int injected_noise;
} rig_t;

static void rig_init(rig_t *r, f32 rpm)
{
    r->cfg = decoder_config_b48();
    decoder_init(&r->dec, &r->cfg);
    r->true_angle = 0.0f;
    r->t = 1000000u;
    r->rpm = rpm;
    r->cam_adv[0] = 0.0f;
    r->cam_adv[1] = 0.0f;
    r->cam_slew[0] = 0.0f;
    r->cam_slew[1] = 0.0f;
    r->drop_cam_edges = 0;
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

    /* Every cam edge the crank just swept past, on both cams, with the
     * pattern displaced by that cam's current advance. */
    for (u8 cam = 0; cam < 2u; cam++) {
        const dec_cam_pattern_t *cp = &r->cfg.cam[cam];
        cam_sim_hit_t hit[DEC_MAX_CAM_EDGES];
        u8 nh = cam_sim_crossed(cp, before, r->true_angle, r->cam_adv[cam],
                                hit, DEC_MAX_CAM_EDGES);
        for (u8 k = 0; k < nh; k++) {
            if (r->drop_cam_edges > 0) { r->drop_cam_edges--; continue; }
            tq_time_t at = r->t - dt + (tq_time_t)(hit[k].frac * (f32)dt);
            decoder_on_cam_edge(&r->dec, cam, at, cp->e[hit[k].idx].rising);
        }
        /* A moving phaser displaces the pattern as the engine turns --
         * and stops dead at its mechanical travel limit, which is why
         * the decoder is entitled to call anything beyond that a jumped
         * chain rather than a fast phaser. */
        r->cam_adv[cam] += r->cam_slew[cam] * (f32)dt * 1.0e-6f;
        if (r->cam_slew[cam] != 0.0f) {
            r->cam_adv[cam] = tq_clampf(r->cam_adv[cam],
                                        cp->adv_min_deg, cp->adv_max_deg);
        }
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


    /* ---- VANOS: the whole point of the multi-tooth cam -------------- */

    TQ_CASE("phase is acquired across the phaser's FULL authority");
    {
        /* The regression that matters. The single-edge decoder rejected
         * any cam more than cam_tolerance_deg from nominal, so past ~25
         * crank degrees of advance it never reached FULL_SYNC at all --
         * and since sched.c gates every spark and injector on
         * decoder_has_phase(), the engine cranked and never fired. A real
         * intake phaser has roughly 70 crank degrees of travel, so that
         * was most of its range. */
        int failures = 0;
        for (f32 adv = 0.0f; adv <= 70.0f; adv += 5.0f) {
            rig_t a;
            rig_init(&a, 900.0f);
            a.cam_adv[0] = adv;
            a.cam_adv[1] = 0.0f;
            spin(&a, 8 * TEETH, 0.0f);
            if (a.dec.state != DEC_FULL_SYNC) failures++;
        }
        TQ_CHECK(failures == 0,
                 "%d of 15 advance positions never reached full sync", failures);
        TQ_PASS("syncs anywhere in the intake phaser's travel");
    }

    TQ_CASE("an exhaust cam that parks ADVANCED and retards also syncs");
    {
        /* Exhaust travel is negative from park. A design carrying a
         * single unsigned "authority" cannot express that and rejects a
         * healthy exhaust cam on every edge. */
        int failures = 0;
        for (f32 adv = 0.0f; adv >= -55.0f; adv -= 5.0f) {
            rig_t a;
            rig_init(&a, 900.0f);
            a.cam_adv[0] = 0.0f;
            a.cam_adv[1] = adv;
            spin(&a, 8 * TEETH, 0.0f);
            if (a.dec.state != DEC_FULL_SYNC) failures++;
            f32 m;
            if (!decoder_cam_advance(&a.dec, 1u, a.t, &m, NULL)) failures++;
        }
        TQ_CHECK(failures == 0, "%d failures across exhaust travel", failures);
        TQ_PASS("negative (exhaust) advance is measured, not rejected");
    }

    TQ_CASE("cam advance is measured, and measured accurately");
    {
        for (f32 adv = 0.0f; adv <= 60.0f; adv += 20.0f) {
            rig_t a;
            rig_init(&a, 1500.0f);
            a.cam_adv[0] = adv;
            spin(&a, 10 * TEETH, 0.0f);
            f32 m = 0.0f;
            u32 age = 0;
            TQ_CHECK(decoder_cam_advance(&a.dec, 0u, a.t, &m, &age),
                     "no advance measurement at %.0f deg", (double)adv);
            TQ_NEAR(m, adv, 1.0f, "advance at %.0f", (double)adv);
        }
        TQ_PASS("reports cam position in crank degrees");
    }

    TQ_CASE("a phaser slewing during acquisition still locks");
    {
        rig_t a;
        rig_init(&a, 1200.0f);
        a.cam_slew[0] = 250.0f;          /* crank deg/s, a brisk move */
        spin(&a, 10 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC,
                 "lost phase while the cam was moving (state %d)", a.dec.state);
        TQ_PASS("acquires phase while the cam is travelling");
    }

    TQ_CASE("one dropped cam edge does not cost the lock");
    {
        rig_t a;
        rig_init(&a, 1500.0f);
        spin(&a, 8 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "precondition");
        a.drop_cam_edges = 1;            /* swallow the next cam edge */
        spin(&a, 4 * TEETH, 0.0f);
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC,
                 "a single dropped cam edge broke phase (state %d)",
                 a.dec.state);
        TQ_PASS("absorbs a dropped cam edge");
    }

    TQ_CASE("a jumped timing chain is detected and latches");
    {
        /* The pattern still matches perfectly -- the wheel is undamaged --
         * but it sits bodily outside the phaser's mechanical travel.
         * That is what a jumped chain looks like, and it is the failure
         * that bends valves. The single-edge decoder could not see it:
         * its tolerance had to be wide enough to pass a moving phaser,
         * which is wide enough to pass a jumped chain too. */
        rig_t a;
        rig_init(&a, 1200.0f);
        a.cam_adv[0] = 200.0f;           /* far outside 0..70 */
        a.cam_adv[1] = 200.0f;
        spin(&a, 12 * TEETH, 0.0f);
        TQ_CHECK(a.dec.chain_fault, "a jumped chain went undetected");
        TQ_CHECK(a.dec.state != DEC_FULL_SYNC,
                 "claimed phase with a jumped chain (state %d)", a.dec.state);
        TQ_PASS("catches a jumped chain");

        /* And it does not un-latch itself by resyncing. */
        a.cam_adv[0] = 0.0f;
        a.cam_adv[1] = 0.0f;
        spin(&a, 20 * TEETH, 0.0f);
        TQ_CHECK(a.dec.chain_fault, "chain fault cleared itself");
        TQ_CHECK(a.dec.state != DEC_FULL_SYNC,
                 "resumed firing after a suspected jumped chain");
        TQ_PASS("a suspected jumped chain needs a human, not a key cycle");
    }

    TQ_CASE("a faulted cam cannot hand the job to its neighbour");
    {
        rig_t a;
        rig_init(&a, 1200.0f);
        a.cam_adv[0] = 200.0f;           /* cam 0 is lying */
        a.cam_adv[1] = 0.0f;             /* cam 1 looks perfect */
        spin(&a, 16 * TEETH, 0.0f);
        TQ_CHECK(a.dec.chain_fault, "no fault raised");
        TQ_CHECK(a.dec.state != DEC_FULL_SYNC,
                 "the healthy cam granted phase anyway (state %d)",
                 a.dec.state);
        TQ_PASS("one bad cam stops the engine, it does not get outvoted");
    }

    TQ_CASE("cam advance goes invalid when sync is lost, never stale");
    {
        /* A phaser loop is an integrating plant. Handed a frozen
         * measurement it winds up and drives the cam into its stop, so
         * "no measurement" must be reported as such rather than as the
         * last good number. */
        rig_t a;
        rig_init(&a, 1500.0f);
        a.cam_adv[0] = 40.0f;
        spin(&a, 10 * TEETH, 0.0f);
        f32 m = 0.0f;
        TQ_CHECK(decoder_cam_advance(&a.dec, 0u, a.t, &m, NULL),
                 "precondition: no measurement");
        decoder_check_timeout(&a.dec, a.t + 500000u);     /* engine stopped */
        TQ_CHECK(!decoder_cam_advance(&a.dec, 0u, a.t, &m, NULL),
                 "kept serving a stale cam position after sync loss");
        TQ_PASS("refuses to serve a stale cam position");
    }

    TQ_CASE("phase arrives sooner than the single-edge decoder managed");
    {
        /* The old design needed crank sync and then had to wait for the
         * one cam edge in the cycle. Three edges per cycle, each of which
         * narrows the candidate set, gets there in less of a turn. */
        rig_t a;
        rig_init(&a, 250.0f);            /* cranking speed */
        int teeth = 0;
        while (a.dec.state != DEC_FULL_SYNC && teeth < 10 * TEETH) {
            step_tooth(&a, 0.0f);
            teeth++;
        }
        TQ_CHECK(a.dec.state == DEC_FULL_SYNC, "never synced while cranking");
        TQ_CHECK(teeth < 4 * TEETH,
                 "took %d teeth (%.1f revolutions) to reach phase",
                 teeth, (double)teeth / (double)TEETH);
        TQ_PASS("phase inside four crank revolutions from a standing start");
    }

    return tq_report("decoder");
}
