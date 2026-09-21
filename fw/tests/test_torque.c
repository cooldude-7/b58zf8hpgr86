/* The torque path and the throttle that serves it.
 *
 * This is the architecture's central claim under test: that the pedal
 * asks for newton-metres, that everything else asking for torque can be
 * arbitrated in the same currency, and that the inverse model turns the
 * winner into something an actuator can chase.
 */
#include <math.h>

#include "engine_rig.h"
#include "throttle.h"
#include "torque.h"
#include "tq_test.h"

static tq_coord_in_t base_in(f32 pedal, f32 rpm)
{
    tq_coord_in_t in;
    in.pedal_pct = pedal;
    in.rpm = rpm;
    in.clt_k = 363.0f;
    in.ve = 0.90f;
    in.map_kpa = 95.0f;
    in.iat_k = 298.0f;
    in.spark_deg = 20.0f;
    in.mbt_deg = 22.0f;
    in.lambda = 1.0f;
    in.running = true;
    in.dt = 0.001f;
    in.limit_nm = -1.0f;
    return in;
}

int main(void)
{
    tq_coord_config_t cfg = tq_coord_config_default();
    tq_engine_t eng = tq_engine_default();

    TQ_CASE("the pedal asks for torque, and full pedal means full torque");
    {
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t in = base_in(100.0f, 3000.0f);
        tq_coord_update(&c, &cfg, &in, &eng);
        TQ_NEAR(c.driver_nm, cfg.max_torque_nm, 1.0f, "full pedal");

        in = base_in(0.0f, 3000.0f);
        tq_coord_update(&c, &cfg, &in, &eng);
        TQ_NEAR(c.driver_nm, 0.0f, 1.0f, "closed pedal");
        TQ_PASS("the pedal map spans the range");
    }

    TQ_CASE("the pedal map is progressive, not linear");
    {
        /* A linear pedal feels darty off idle, because the first few
         * percent of travel move a lot of air. Half pedal should ask for
         * appreciably less than half torque. */
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t in = base_in(50.0f, 3000.0f);
        tq_coord_update(&c, &cfg, &in, &eng);
        TQ_CHECK(c.driver_nm < 0.45f * cfg.max_torque_nm,
                 "half pedal asked for %.0f of %.0f Nm",
                 (double)c.driver_nm, (double)cfg.max_torque_nm);
        TQ_PASS("resolution where the driver needs it");
    }

    TQ_CASE("idle asks for torque when the engine is falling below target");
    {
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t in = base_in(0.0f, 600.0f);   /* below a hot idle */
        for (int i = 0; i < 500; i++) tq_coord_update(&c, &cfg, &in, &eng);
        TQ_CHECK(c.idle_nm > 5.0f, "idle asked for only %.1f Nm",
                 (double)c.idle_nm);
        TQ_CHECK(c.target_nm >= c.idle_nm - 0.01f,
                 "arbitration dropped the idle request");
        TQ_PASS("idle is a torque requestor like anything else");
    }

    TQ_CASE("idle asks for nothing well above its target, and does not wind up");
    {
        /* The failure this prevents: an integrator quietly accumulating
         * while the driver is at speed, then dumping its whole demand
         * the moment they lift. */
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t in = base_in(0.0f, 4000.0f);
        for (int i = 0; i < 2000; i++) tq_coord_update(&c, &cfg, &in, &eng);
        TQ_NEAR(c.idle_nm, 0.0f, 0.01f, "idle asked for torque at 4000 rpm");
        TQ_NEAR(c.idle_i, 0.0f, 0.01f, "the idle integrator wound up");
        TQ_PASS("no windup above the band");
    }

    TQ_CASE("the idle target rises when the engine is cold");
    {
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t cold = base_in(0.0f, 900.0f); cold.clt_k = 253.0f;
        tq_coord_update(&c, &cfg, &cold, &eng);
        f32 cold_rpm = c.idle_target_rpm;
        tq_coord_in_t hot = base_in(0.0f, 900.0f); hot.clt_k = 363.0f;
        tq_coord_update(&c, &cfg, &hot, &eng);
        TQ_CHECK(cold_rpm > c.idle_target_rpm + 200.0f,
                 "cold idle %.0f vs hot %.0f", (double)cold_rpm,
                 (double)c.idle_target_rpm);
        TQ_PASS("a cold engine idles faster");
    }

    TQ_CASE("a torque limit cuts the target, whatever the pedal says");
    {
        tq_coord_t c; tq_coord_init(&c, &cfg);
        tq_coord_in_t in = base_in(100.0f, 3000.0f);
        in.limit_nm = 80.0f;
        tq_coord_update(&c, &cfg, &in, &eng);
        TQ_NEAR(c.target_nm, 80.0f, 0.01f, "the limit was not applied");
        TQ_CHECK(c.driver_nm > 300.0f, "the driver request was altered");
        TQ_PASS("limits arbitrate in the same currency");
    }

    TQ_CASE("the manifold target actually delivers the air that was asked for");
    {
        /* The round trip that makes the whole structure coherent: the
         * inverse model says how much air the torque needs, and the
         * pressure target has to be the pressure that produces exactly
         * that air through the SAME air model the fuel path uses. If
         * these two disagree the engine fuels for one number and
         * breathes another. */
        tq_coord_t c; tq_coord_init(&c, &cfg);
        for (f32 pedal = 20.0f; pedal <= 100.0f; pedal += 20.0f) {
            tq_coord_in_t in = base_in(pedal, 3000.0f);
            tq_coord_update(&c, &cfg, &in, &eng);
            f32 delivered = tq_air_mass(in.ve, c.map_target_kpa,
                                        in.iat_k + 15.0f, &eng);
            TQ_NEAR(delivered, c.air_target_g,
                    0.02f * c.air_target_g + 1e-4f,
                    "at %.0f %% pedal the target pressure delivers %.4f g "
                    "but the model wanted %.4f g",
                    (double)pedal, (double)delivered, (double)c.air_target_g);
        }
        TQ_PASS("air target and pressure target agree");
    }

    /* ---- the throttle that has to chase it -------------------------- */

    TQ_CASE("the throttle converges on its pressure target");
    {
        thr_config_t tc = thr_config_default();
        throttle_t t; throttle_init(&t, &tc);
        thr_plant_t plate; thr_plant_init(&plate, 7.0f);

        /* A crude manifold: pressure follows plate position with a lag,
         * which is the behaviour the outer loop exists to handle. */
        f32 map = 30.0f;
        for (int i = 0; i < 4000; i++) {
            thr_in_t in;
            in.dt = 0.001f;
            in.map_target_kpa = 160.0f;
            in.map_actual_kpa = map;
            in.tps_a_pct = plate.pos_pct;
            in.tps_b_pct = plate.pos_pct;
            in.allow = true;
            throttle_update(&t, &tc, &in);
            thr_plant_step(&plate, t.duty, t.enabled, 0.001f);
            f32 want = 25.0f + plate.pos_pct * 2.2f;
            map += (want - map) * (0.001f / 0.08f);
        }
        TQ_NEAR(map, 160.0f, 6.0f, "manifold settled at %.0f kPa",
                (double)map);
        TQ_PASS("the cascade closes on pressure");
    }

    TQ_CASE("throttle sensors that disagree open the bridge");
    {
        /* If the two sensors disagree we do not know where the plate is,
         * and a position loop run on a number that might be wrong drives
         * it somewhere nobody asked for. */
        thr_config_t tc = thr_config_default();
        throttle_t t; throttle_init(&t, &tc);
        thr_in_t in;
        in.dt = 0.001f;
        in.map_target_kpa = 160.0f;
        in.map_actual_kpa = 90.0f;
        in.tps_a_pct = 60.0f;
        in.tps_b_pct = 10.0f;
        in.allow = true;
        throttle_update(&t, &tc, &in);
        TQ_CHECK(!t.plausible, "believed two sensors 50 %% apart");
        TQ_CHECK(!t.enabled, "kept driving the bridge");
        TQ_NEAR(t.duty, 0.0f, 1e-6f, "left duty on the bridge");
        TQ_PASS("gives up rather than guessing");
    }

    TQ_CASE("a disabled throttle reports the limp position as its command");
    {
        /* Otherwise the Level 2 tracking check compares a command the
         * controller was never going to follow against the position the
         * spring actually chose, and limps the car for it. */
        thr_config_t tc = thr_config_default();
        throttle_t t; throttle_init(&t, &tc);
        thr_in_t in;
        in.dt = 0.001f;
        in.map_target_kpa = 200.0f;
        in.map_actual_kpa = 90.0f;
        in.tps_a_pct = 7.0f;
        in.tps_b_pct = 7.0f;
        in.allow = false;
        throttle_update(&t, &tc, &in);
        TQ_NEAR(t.cmd_pct, tc.limp_pos_pct, 0.01f,
                "commanded %.1f with the bridge open", (double)t.cmd_pct);
        TQ_PASS("command and reality agree when the spring is in charge");
    }

    return tq_report("torque");
}
