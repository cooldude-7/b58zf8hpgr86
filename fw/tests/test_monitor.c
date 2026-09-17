/* The C monitor must behave exactly like the Python one: the safety
 * tests in tests/test_safety.py are written against that behaviour, and
 * a port that differs quietly makes those tests meaningless. */
#include "monitor.h"
#include "tq_test.h"

static mon_inputs_t nominal(void)
{
    mon_inputs_t in;
    in.dt = 0.01f;
    in.pedal_a = in.pedal_b = 50.0f;
    in.tps_a = in.tps_b = in.tps_cmd = 50.0f;
    in.torque = 100.0f;
    in.rpm = 3000.0f;
    in.max_torque = 400.0f;
    in.rev_limit = 7200.0f;
    in.map_kpa = 150.0f;
    in.overboost_kpa = 265.0f;
    return in;
}

static mon_limp_t run(tq_monitor_t *m, int n, mon_inputs_t in)
{
    mon_limp_t out = MON_OK;
    for (int i = 0; i < n; i++) out = tq_monitor_update(m, &in);
    return out;
}

int main(void)
{
    tq_monitor_t m;

    TQ_CASE("nominal driving raises nothing");
    tq_monitor_reset(&m);
    TQ_CHECK(run(&m, 200, nominal()) == MON_OK, "limp %d", m.limp);
    TQ_CHECK(m.fault == MON_F_NONE, "fault %d", m.fault);
    TQ_PASS("clean at steady state");

    TQ_CASE("pedal disagreement is caught");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.pedal_a = 80.0f; in.pedal_b = 10.0f; in.torque = 50.0f;
        TQ_CHECK(run(&m, 30, in) >= MON_REDUCED, "no limp");
        TQ_CHECK(m.fault == MON_F_PEDAL_PLAUSIBILITY, "fault %d", m.fault);
        TQ_PASS("pedal plausibility");
    }

    TQ_CASE("a single bad sample is not a fault");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.pedal_a = 80.0f; in.pedal_b = 10.0f;
        TQ_CHECK(run(&m, 2, in) == MON_OK, "tripped on 20 ms of disagreement");
        TQ_PASS("debounce works");
    }

    TQ_CASE("throttle disagreement drops to idle only");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.tps_a = 80.0f; in.tps_b = 10.0f; in.tps_cmd = 80.0f;
        TQ_CHECK(run(&m, 30, in) >= MON_IDLE_ONLY, "limp %d", m.limp);
    }

    TQ_CASE("unrequested torque is caught");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.pedal_a = in.pedal_b = 0.0f;
        in.tps_a = in.tps_b = in.tps_cmd = 0.0f;
        in.torque = 390.0f;
        TQ_CHECK(run(&m, 40, in) >= MON_IDLE_ONLY, "limp %d", m.limp);
        TQ_CHECK(m.fault == MON_F_TORQUE_EXCEEDS_PERMISSIBLE, "fault %d", m.fault);
        TQ_PASS("torque monitor");
    }

    TQ_CASE("idle torque at zero pedal is allowed");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.pedal_a = in.pedal_b = 0.0f;
        in.tps_a = in.tps_b = in.tps_cmd = 0.0f;
        in.torque = 35.0f; in.rpm = 800.0f;
        TQ_CHECK(run(&m, 60, in) == MON_OK, "limped at idle");
    }

    TQ_CASE("overspeed and overboost shut down");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal(); in.rpm = 9000.0f;
        TQ_CHECK(run(&m, 5, in) == MON_SHUTDOWN, "no shutdown on overspeed");
        tq_monitor_reset(&m);
        in = nominal(); in.map_kpa = 300.0f;
        TQ_CHECK(run(&m, 5, in) == MON_SHUTDOWN, "no shutdown on overboost");
        TQ_PASS("hard limits shut down");
    }

    TQ_CASE("a limp latches until reset");
    {
        tq_monitor_reset(&m);
        mon_inputs_t bad = nominal();
        bad.pedal_a = 80.0f; bad.pedal_b = 10.0f;
        run(&m, 30, bad);
        mon_limp_t after_bad = m.limp;
        run(&m, 200, nominal());
        TQ_CHECK(m.limp == after_bad, "limp cleared itself");
        tq_monitor_reset(&m);
        TQ_CHECK(m.limp == MON_OK, "reset did not clear");
        TQ_PASS("latching");
    }

    TQ_CASE("the root cause is kept, not the last symptom");
    {
        tq_monitor_reset(&m);
        mon_inputs_t in = nominal();
        in.pedal_a = 80.0f; in.pedal_b = 10.0f; in.torque = 390.0f;
        run(&m, 100, in);
        TQ_CHECK(m.fault == MON_F_PEDAL_PLAUSIBILITY, "fault %d", m.fault);
        TQ_CHECK(m.fault_mask & (1u << MON_F_TORQUE_EXCEEDS_PERMISSIBLE),
                 "the consequent fault was not recorded");
        TQ_PASS("root cause preserved");
    }

    TQ_CASE("torque cap per limp level");
    {
        tq_monitor_reset(&m);
        TQ_NEAR(tq_monitor_torque_cap(&m, 400.0f), 400.0f, 1e-6, "ok");
        m.limp = MON_REDUCED;
        TQ_NEAR(tq_monitor_torque_cap(&m, 400.0f), 200.0f, 1e-6, "reduced");
        m.limp = MON_IDLE_ONLY;
        TQ_NEAR(tq_monitor_torque_cap(&m, 400.0f), 30.0f, 1e-6, "idle only");
        m.limp = MON_SHUTDOWN;
        TQ_NEAR(tq_monitor_torque_cap(&m, 400.0f), 0.0f, 1e-6, "shutdown");
        TQ_PASS("caps match the Python");
    }

    return tq_report("monitor");
}
