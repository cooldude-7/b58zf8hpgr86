/* Wastegate and boost control against a turbo that behaves like one.
 *
 * The plant matters as much as the controller here. A wastegate is a
 * motor with a position sensor, so there are two loops stacked -- gate
 * position, then manifold pressure -- and the outer one runs through a
 * turbine that takes a few hundred milliseconds to respond. A test that
 * wires the commanded position straight to the pressure proves the
 * arithmetic and nothing about the loop.
 *
 * The sign is the trap: everywhere else in this firmware more output
 * means more air, and here MORE gate opening means LESS.
 */
#include <math.h>

#include "boost.h"
#include "hal_host.h"
#include "tq_test.h"

#define AMBIENT_KPA 100.0f

typedef struct {
    f32 gate;          /* true position, 0 = shut, 100 = wide open */
    f32 rate;          /* percent per second at full duty */
    bool seized;

    f32 map;           /* manifold pressure */
    f32 boost_max;     /* what a fully shut gate is worth, above ambient */
    f32 tau;           /* how long the turbine takes to get there */
    f32 authority;     /* 0 off throttle, 1 at wide open: no exhaust energy,
                        * no boost, whatever the gate is doing */
} turbo_t;

static turbo_t turbo_default(void)
{
    turbo_t t;
    t.gate = 100.0f;
    t.rate = 400.0f;
    t.seized = false;
    t.map = AMBIENT_KPA;
    t.boost_max = 160.0f;
    t.tau = 0.30f;
    t.authority = 1.0f;
    return t;
}

static void turbo_step(turbo_t *t, f32 duty, f32 dt)
{
    if (!t->seized) {
        t->gate = tq_clampf(t->gate + duty * t->rate * dt, 0.0f, 100.0f);
    }
    f32 ss = AMBIENT_KPA
           + t->boost_max * t->authority * (1.0f - t->gate * 0.01f);
    t->map += (ss - t->map) * (dt / t->tau);
}

/* One slow-task tick. Returns the controller's commanded position. */
static void tick(boost_t *b, const boost_config_t *cfg, turbo_t *t,
                 f32 target_kpa, f32 tps_pct, bool running, bool sensor_ok,
                 f32 dt)
{
    boost_in_t in;
    in.dt = dt;
    in.map_target_kpa = target_kpa;
    in.map_actual_kpa = t->map;
    in.gate_pct = t->gate;
    in.tps_pct = tps_pct;
    in.running = running;
    in.sensor_ok = sensor_ok;
    boost_update(b, cfg, &in);
    turbo_step(t, b->duty, dt);
}

static f32 settle(boost_t *b, const boost_config_t *cfg, turbo_t *t,
                  f32 target_kpa, f32 seconds)
{
    const f32 dt = 0.01f;           /* the slow task's rate */
    u32 n = (u32)(seconds / dt);
    for (u32 i = 0; i < n; i++) {
        tick(b, cfg, t, target_kpa, 80.0f, true, true, dt);
    }
    return t->map;
}

int main(void)
{
    boost_config_t cfg = boost_config_default();

    TQ_CASE("the gate closes to raise manifold pressure");
    {
        /* The whole sign convention in one check. If this is backwards
         * the controller runs away to a rail on the first tip-in and the
         * engine either makes no boost at all or all of it. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();

        f32 map = settle(&b, &cfg, &t, 190.0f, 6.0f);
        TQ_NEAR(map, 190.0f, 6.0f, "settled at %.0f kPa, wanted 190", map);
        TQ_CHECK(b.cmd_pct > 1.0f && b.cmd_pct < 99.0f,
                 "gate parked on a rail at %.1f %% instead of regulating",
                 b.cmd_pct);
        TQ_CHECK(fabsf(t.gate - b.cmd_pct) < 2.0f,
                 "the inner loop did not track: commanded %.1f, actual %.1f",
                 b.cmd_pct, t.gate);
        TQ_PASS("closed loop reaches target");
    }

    TQ_CASE("more boost wanted means less gate opening");
    {
        boost_t lo, hi;
        boost_init(&lo, &cfg);
        boost_init(&hi, &cfg);
        turbo_t tlo = turbo_default(), thi = turbo_default();

        settle(&lo, &cfg, &tlo, 160.0f, 6.0f);
        settle(&hi, &cfg, &thi, 220.0f, 6.0f);
        TQ_CHECK(hi.cmd_pct < lo.cmd_pct,
                 "220 kPa asked for %.1f %% gate, 160 kPa asked for %.1f %%",
                 hi.cmd_pct, lo.cmd_pct);
        TQ_PASS("monotonic in target");
    }

    TQ_CASE("a target below ambient does not ask for a negative opening");
    {
        /* Off boost the throttle is doing the regulating and the gate
         * has nothing useful to contribute. What it must not do is wind
         * itself into a corner it then has to climb out of. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        t.authority = 0.0f;                 /* idling: no exhaust energy */

        for (u32 i = 0; i < 600; i++) {
            tick(&b, &cfg, &t, 40.0f, 6.0f, true, true, 0.01f);
            TQ_CHECK(b.cmd_pct >= 0.0f && b.cmd_pct <= 100.0f,
                     "commanded %.1f %%", b.cmd_pct);
            if (tq_fails) break;
        }
        TQ_NEAR(b.cmd_pct, 100.0f, 0.001f,
                "gate not held open with nothing to regulate");
        TQ_CHECK(fabsf(b.map_i) <= cfg.map_i_max + 1e-3f,
                 "integrator ran to %.1f against a clamp of %.1f",
                 b.map_i, cfg.map_i_max);
        TQ_PASS("no windup below ambient");
    }

    TQ_CASE("overboost opens the gate ahead of the loop");
    {
        /* Not inside the PI loop: a controller winding its way back from
         * an overshoot is not a protection, it is a delay. One tick. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        settle(&b, &cfg, &t, 220.0f, 6.0f);
        TQ_CHECK(b.cmd_pct < 90.0f, "setup did not close the gate");

        t.map = cfg.overboost_kpa + 5.0f;
        tick(&b, &cfg, &t, 220.0f, 80.0f, true, true, 0.01f);
        TQ_NEAR(b.cmd_pct, 100.0f, 0.001f,
                "overboost left the gate at %.1f %%", b.cmd_pct);
        TQ_NEAR(b.map_i, 0.0f, 1e-6, "the integrator survived an overboost");
        TQ_CHECK(b.duty > 0.0f, "the bridge was not driven toward open");
        TQ_PASS("overboost overrides");
    }

    TQ_CASE("a lift holds the gate, then lets it go");
    {
        /* Holding the gate shut on a lift keeps the turbine spinning,
         * which is what makes the noise people fit blow-off valves to
         * avoid. The hold is deliberate; holding it forever is not --
         * an overrun down a long hill would spin the compressor against
         * a shut throttle for as long as the driver stayed off it. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        settle(&b, &cfg, &t, 220.0f, 6.0f);

        /* Throttle closed, and it stays closed. */
        tick(&b, &cfg, &t, 220.0f, 0.0f, true, true, 0.01f);
        TQ_CHECK(b.lifting, "a closed throttle did not register as a lift");
        TQ_NEAR(b.cmd_pct, cfg.lift_hold_pct, 0.001f,
                "the gate was not held at %.0f %%", cfg.lift_hold_pct);

        f32 held_s = 0.0f;
        for (u32 i = 0; i < 1000 && b.lifting; i++) {
            tick(&b, &cfg, &t, 220.0f, 0.0f, true, true, 0.01f);
            held_s += 0.01f;
        }
        TQ_CHECK(!b.lifting, "the hold never expired with the throttle shut");
        TQ_NEAR(held_s, cfg.lift_hold_s, 0.05f,
                "held for %.2f s, calibrated for %.2f", held_s,
                cfg.lift_hold_s);

        /* And it does not re-arm itself while the throttle stays shut. */
        for (u32 i = 0; i < 300; i++) {
            tick(&b, &cfg, &t, 220.0f, 0.0f, true, true, 0.01f);
            TQ_CHECK(!b.lifting, "the hold re-armed without a throttle press");
            if (tq_fails) break;
        }
        TQ_PASS("lift hold expires");
    }

    TQ_CASE("the next lift gets its own hold");
    {
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        settle(&b, &cfg, &t, 220.0f, 6.0f);

        for (u32 i = 0; i < 400; i++) {           /* lift, hold, expire */
            tick(&b, &cfg, &t, 220.0f, 0.0f, true, true, 0.01f);
        }
        TQ_CHECK(!b.lifting, "setup left it holding");

        tick(&b, &cfg, &t, 220.0f, 80.0f, true, true, 0.01f);   /* back on it */
        tick(&b, &cfg, &t, 220.0f, 0.0f, true, true, 0.01f);    /* lift again */
        TQ_CHECK(b.lifting, "the second lift got no hold");
        TQ_NEAR(b.cmd_pct, cfg.lift_hold_pct, 0.001f, "not held");
        TQ_PASS("lift re-arms on throttle");
    }

    TQ_CASE("a lost position sensor opens the bridge");
    {
        /* A gate whose position is unknown must not be driven toward
         * closed, because closed is the direction that ends in a
         * cracked piston rather than a slow car. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        settle(&b, &cfg, &t, 220.0f, 6.0f);
        TQ_CHECK(hal_host_bridge_enabled(HAL_BRIDGE_WASTEGATE),
                 "setup left the bridge off");

        tick(&b, &cfg, &t, 220.0f, 80.0f, true, false, 0.01f);
        TQ_CHECK(!hal_host_bridge_enabled(HAL_BRIDGE_WASTEGATE),
                 "the bridge stayed live with no position feedback");
        TQ_CHECK(!b.enabled, "the controller still thinks it is in charge");
        TQ_NEAR(b.cmd_pct, cfg.open_pct, 0.001f, "gate not parked open");
        TQ_NEAR(b.map_i, 0.0f, 1e-6, "outer integrator kept its charge");
        TQ_NEAR(b.pos_i, 0.0f, 1e-6, "inner integrator kept its charge");
        TQ_PASS("sensor fault opens the bridge");
    }

    TQ_CASE("a stopped engine does not wind up");
    {
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        for (u32 i = 0; i < 2000; i++) {
            tick(&b, &cfg, &t, 220.0f, 0.0f, false, true, 0.01f);
        }
        TQ_NEAR(b.map_i, 0.0f, 1e-6, "integrator wound up with the engine off");
        TQ_NEAR(b.duty, 0.0f, 1e-6, "the bridge was driven with the engine off");
        TQ_CHECK(!hal_host_bridge_enabled(HAL_BRIDGE_WASTEGATE),
                 "bridge live with the engine stopped");
        TQ_PASS("no windup while stopped");
    }

    TQ_CASE("a seized gate is recovered from immediately");
    {
        /* The point of anti-windup, stated as the failure it prevents:
         * after a long saturated stretch the controller has to be able
         * to act on the FIRST tick where the error reverses, not after
         * unwinding a charge it should never have accumulated. */
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        t.gate = 0.0f;
        t.seized = true;
        t.map = 150.0f;

        for (u32 i = 0; i < 3000; i++) {           /* 30 s hard against it */
            tick(&b, &cfg, &t, 300.0f, 80.0f, true, true, 0.01f);
        }
        TQ_CHECK(fabsf(b.map_i) <= cfg.map_i_max + 1e-3f,
                 "outer integrator at %.1f against a clamp of %.1f",
                 b.map_i, cfg.map_i_max);
        TQ_CHECK(fabsf(b.pos_i) <= cfg.pos_i_max + 1e-3f,
                 "inner integrator at %.3f against a clamp of %.3f",
                 b.pos_i, cfg.pos_i_max);

        t.seized = false;
        t.map = 320.0f;                             /* error reverses hard */
        tick(&b, &cfg, &t, 300.0f, 80.0f, true, true, 0.01f);
        TQ_CHECK(b.cmd_pct > 20.0f,
                 "after saturating, the first reversed tick only reached "
                 "%.1f %%", b.cmd_pct);
        TQ_PASS("anti-windup on both loops");
    }

    TQ_CASE("duty is bounded and reaches the bridge");
    {
        boost_t b;
        boost_init(&b, &cfg);
        turbo_t t = turbo_default();
        t.map = 100.0f;
        for (u32 i = 0; i < 2000; i++) {
            /* A target nothing can deliver, so the loop lives on its
             * limits for the whole run. */
            tick(&b, &cfg, &t, 400.0f, 80.0f, true, true, 0.01f);
            TQ_CHECK(b.duty >= -1.0f && b.duty <= 1.0f,
                     "duty %.3f out of range", b.duty);
            TQ_NEAR(hal_host_bridge(HAL_BRIDGE_WASTEGATE), b.duty, 1e-6,
                    "the bridge did not get what was commanded");
            if (tq_fails) break;
        }
        TQ_PASS("duty bounded");
    }

    return tq_report("boost");
}
