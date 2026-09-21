/* The corrections that turn an engine model into an engine.
 *
 * Every case here is a way a car misbehaves that the steady-state model
 * cannot see: it will not start cold, it fires once and dies, it
 * stumbles on tip-in, it runs rich on the overrun.
 */
#include "enrich.h"
#include "tq_test.h"

static enr_in_t base(f32 clt_k, f32 rpm)
{
    enr_in_t in;
    in.dt = 0.001f;
    in.rpm = rpm;
    in.clt_k = clt_k;
    in.map_kpa = 40.0f;
    in.tps_pct = 20.0f;
    in.cranking = false;
    in.running = true;
    return in;
}

int main(void)
{
    enr_config_t cfg = enr_config_default();

    TQ_CASE("a cold engine gets far more fuel while cranking");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(253.0f, 200.0f);   /* -20 C, on the starter */
        in.cranking = true;
        in.running = false;
        enrich_update(&e, &cfg, &in);
        f32 cold = e.crank;

        enrich_init(&e);
        in = base(363.0f, 200.0f);            /* +90 C */
        in.cranking = true;
        in.running = false;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(cold > e.crank * 2.0f,
                 "cold crank %.2f is not much richer than hot %.2f",
                 (double)cold, (double)e.crank);
        TQ_CHECK(cold > 3.0f, "cold cranking enrichment is only %.2f",
                 (double)cold);
        TQ_PASS("it can light a cold engine");
    }

    TQ_CASE("the after-start decay starts when it CATCHES, not at key-on");
    {
        /* A long crank would otherwise use up the whole after-start
         * period before the first firing, and the engine dies just after
         * it starts -- which reads as a fuel supply problem. */
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(293.0f, 250.0f);
        in.cranking = true;
        in.running = false;
        for (int i = 0; i < 5000; i++) enrich_update(&e, &cfg, &in);
        TQ_NEAR(e.astart_t, 0.0f, 1e-6f,
                "the after-start clock ran during a 5 second crank");

        in = base(293.0f, 900.0f);            /* it catches */
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(e.astart > 1.3f, "no after-start enrichment (%.2f)",
                 (double)e.astart);
        TQ_PASS("the clock starts at the first firing");
    }

    TQ_CASE("after-start enrichment decays away and stays away");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(293.0f, 250.0f);
        in.cranking = true; in.running = false;
        enrich_update(&e, &cfg, &in);
        in = base(293.0f, 900.0f);
        for (int i = 0; i < 20000; i++) enrich_update(&e, &cfg, &in);
        TQ_NEAR(e.astart, 1.0f, 0.02f, "still enriching after 20 s");
        TQ_PASS("it lets go");
    }

    TQ_CASE("warmup enrichment tapers to nothing when hot");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t cold = base(273.0f, 900.0f);
        enrich_update(&e, &cfg, &cold);
        f32 c = e.warm;
        enr_in_t hot = base(363.0f, 900.0f);
        enrich_update(&e, &cfg, &hot);
        TQ_CHECK(c > e.warm, "cold %.2f is not richer than hot %.2f",
                 (double)c, (double)e.warm);
        TQ_NEAR(e.warm, 1.0f, 0.01f, "still enriching a hot engine");
        TQ_PASS("warmup tapers out");
    }

    TQ_CASE("a fast throttle opening gets extra fuel, a slow one does not");
    {
        /* The manifold fills faster than the fuel film on the port walls
         * re-establishes, so the cylinder goes momentarily lean. */
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(363.0f, 2000.0f);
        enrich_update(&e, &cfg, &in);
        for (int i = 0; i < 20; i++) {       /* 40 kPa -> 140 in 20 ms */
            in.map_kpa += 5.0f;
            enrich_update(&e, &cfg, &in);
        }
        f32 fast = e.accel;

        enrich_t e2; enrich_init(&e2);
        enr_in_t s2 = base(363.0f, 2000.0f);
        enrich_update(&e2, &cfg, &s2);
        for (int i = 0; i < 2000; i++) {     /* the same rise over 2 s */
            s2.map_kpa += 0.05f;
            enrich_update(&e2, &cfg, &s2);
        }
        TQ_CHECK(fast > 1.05f, "a fast tip-in got only %.3f", (double)fast);
        TQ_CHECK(fast > e2.accel + 0.04f,
                 "fast %.3f and slow %.3f were treated the same",
                 (double)fast, (double)e2.accel);
        TQ_PASS("rate matters, not just position");
    }

    TQ_CASE("acceleration enrichment is worse when cold, as the physics is");
    {
        /* A realistic tip-in: 60 kPa over 100 ms. The earlier version
         * ramped 100 kPa in 20 ms, which is faster than a manifold can
         * physically fill, and it pinned BOTH cases against accel_max --
         * so the test compared two saturated numbers and concluded
         * nothing. */
        enrich_t hot; enrich_init(&hot);
        enr_in_t h = base(363.0f, 2000.0f);
        enrich_update(&hot, &cfg, &h);
        for (int i = 0; i < 100; i++) { h.map_kpa += 0.6f; enrich_update(&hot, &cfg, &h); }

        enrich_t cold; enrich_init(&cold);
        enr_in_t c = base(273.0f, 2000.0f);
        enrich_update(&cold, &cfg, &c);
        for (int i = 0; i < 100; i++) { c.map_kpa += 0.6f; enrich_update(&cold, &cfg, &c); }
        TQ_CHECK(hot.accel < cfg.accel_max - 0.01f,
                 "the hot case saturated, so the comparison proves nothing");

        TQ_CHECK(cold.accel > hot.accel,
                 "cold tip-in %.3f is not richer than hot %.3f",
                 (double)cold.accel, (double)hot.accel);
        TQ_PASS("wall wetting is worse on cold metal");
    }

    TQ_CASE("acceleration enrichment decays rather than latching");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(363.0f, 2000.0f);
        enrich_update(&e, &cfg, &in);
        for (int i = 0; i < 20; i++) { in.map_kpa += 5.0f; enrich_update(&e, &cfg, &in); }
        TQ_CHECK(e.accel > 1.05f, "precondition");
        for (int i = 0; i < 3000; i++) enrich_update(&e, &cfg, &in);
        TQ_NEAR(e.accel, 1.0f, 0.02f, "still enriching 3 s after the tip-in");
        TQ_PASS("it lets go");
    }

    TQ_CASE("closed throttle at speed cuts fuel, with hysteresis");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(363.0f, 3000.0f);
        in.tps_pct = 0.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(e.fuel_cut, "no decel cut at 3000 rpm on a closed throttle");

        /* Coming down: fuel must come back BEFORE idle, not at it. */
        in.rpm = 1200.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(e.fuel_cut, "resumed too early, above the resume speed");
        in.rpm = 1000.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(!e.fuel_cut, "never resumed, and the engine would stall");
        TQ_PASS("hysteresis, so it does not chatter at the threshold");
    }

    TQ_CASE("a cold engine is never decel cut");
    {
        /* A cold engine that is cut may not relight. */
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(283.0f, 3000.0f);   /* 10 C */
        in.tps_pct = 0.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(!e.fuel_cut, "cut fuel on a cold engine");
        TQ_PASS("no cut while cold");
    }

    TQ_CASE("touching the throttle ends the cut immediately");
    {
        enrich_t e; enrich_init(&e);
        enr_in_t in = base(363.0f, 3000.0f);
        in.tps_pct = 0.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(e.fuel_cut, "precondition");
        in.tps_pct = 15.0f;
        enrich_update(&e, &cfg, &in);
        TQ_CHECK(!e.fuel_cut, "kept fuel cut with the throttle open");
        TQ_PASS("the driver wins");
    }

    return tq_report("enrich");
}
