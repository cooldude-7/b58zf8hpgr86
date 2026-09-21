/* Fuel pump, cooling fan, tacho and lamp.
 *
 * None of this is clever and one piece of it is a safety function: the
 * pump has to stop when the engine loses sync, because a pump feeding a
 * broken line after a crash is the failure that rule exists for. The
 * rest is the difference between an engine on a stand and a car -- a fan
 * that chatters at its threshold, or a tacho reading half, is what makes
 * a standalone install feel like a kit.
 */
#include <math.h>

#include "aux.h"
#include "hal_host.h"
#include "tq_test.h"

static aux_in_t running_at(f32 rpm, f32 clt_k)
{
    aux_in_t in;
    in.dt = 0.01f;
    in.rpm = rpm;
    in.clt_k = clt_k;
    in.has_sync = true;
    in.running = true;
    in.faulted = false;
    return in;
}

/* Run for `seconds` and return how long the pump was commanded on. */
static f32 run_for(aux_t *a, const aux_config_t *cfg, aux_in_t *in, f32 seconds)
{
    f32 pump_s = 0.0f;
    u32 n = (u32)(seconds / in->dt + 0.5f);
    for (u32 i = 0; i < n; i++) {
        aux_update(a, cfg, in);
        if (a->pump) pump_s += in->dt;
    }
    return pump_s;
}

int main(void)
{
    aux_config_t cfg = aux_config_default();

    TQ_CASE("the pump primes at key-on, then waits for sync");
    {
        /* Without the prime the first crank happens against an empty
         * low pressure rail, which is most of why a fresh install
         * cranks for five seconds before it catches. */
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(0.0f, 293.0f);
        in.has_sync = false;
        in.running = false;

        aux_update(&a, &cfg, &in);
        TQ_CHECK(a.pump, "the pump did not run at key-on");

        f32 on_s = run_for(&a, &cfg, &in, 10.0f);
        TQ_CHECK(!a.pump, "the pump was still running 10 s after key-on "
                          "with no sync");
        /* Prime, then the same grace a running engine gets. Both are
         * bounded, and the bound is what the test is about. */
        TQ_NEAR(on_s, cfg.prime_s + cfg.pump_sync_grace_s, 0.05f,
                "the pump ran for %.2f s", on_s + 0.01f);
        TQ_PASS("prime then cut");
    }

    TQ_CASE("the pump runs while the engine has sync");
    {
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, 360.0f);
        f32 on_s = run_for(&a, &cfg, &in, 30.0f);
        TQ_NEAR(on_s, 30.0f, 0.02f, "the pump stopped while running");
        TQ_CHECK(hal_host_sw(HAL_SW_FUEL_PUMP), "the output never got set");
        TQ_PASS("pump follows sync");
    }

    TQ_CASE("the pump stops promptly when sync is lost");
    {
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, 360.0f);
        run_for(&a, &cfg, &in, 5.0f);

        in.has_sync = false;
        in.running = false;
        in.rpm = 0.0f;
        f32 on_s = run_for(&a, &cfg, &in, 5.0f);
        TQ_CHECK(!a.pump, "the pump kept running after sync was lost");
        TQ_CHECK(!hal_host_sw(HAL_SW_FUEL_PUMP), "the output stayed live");
        TQ_NEAR(on_s, cfg.pump_sync_grace_s, 0.02f,
                "it took %.2f s to cut, calibrated for %.2f", on_s,
                cfg.pump_sync_grace_s);
        TQ_PASS("pump cuts on lost sync");
    }

    TQ_CASE("a momentary dropout does not stop the pump");
    {
        /* The other half of the same rule. A single missed tooth at
         * 6000 rpm must not cut fuel pressure to an engine that is
         * about to recover on the next one -- that turns a glitch into
         * a stall, and a stall on a motorway into a real problem. */
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(6000.0f, 360.0f);
        run_for(&a, &cfg, &in, 5.0f);

        in.has_sync = false;
        for (u32 i = 0; i < 20; i++) {      /* 200 ms of nothing */
            aux_update(&a, &cfg, &in);
            TQ_CHECK(a.pump, "the pump cut after %u ms without sync", i * 10u);
            if (tq_fails) break;
        }
        in.has_sync = true;
        aux_update(&a, &cfg, &in);
        TQ_NEAR(a.nosync_t, 0.0f, 1e-6, "the dropout timer did not reset");
        TQ_PASS("glitch tolerance");
    }

    TQ_CASE("the fan has hysteresis instead of a threshold");
    {
        /* Same switch-on and switch-off temperature means the fan
         * cycles several times a minute sitting in traffic, which is
         * audible, and hard on the relay. */
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(800.0f, 360.0f);
        run_for(&a, &cfg, &in, 3.0f);
        TQ_CHECK(!a.fan, "the fan is on at 87 C");

        in.clt_k = cfg.fan_on_k + 0.5f;
        aux_update(&a, &cfg, &in);
        TQ_CHECK(a.fan, "the fan did not come on above its threshold");
        TQ_CHECK(hal_host_sw(HAL_SW_FAN), "the fan output never got set");

        /* Between the two thresholds it must hold whatever it was. */
        in.clt_k = (cfg.fan_on_k + cfg.fan_off_k) * 0.5f;
        for (u32 i = 0; i < 500; i++) {
            aux_update(&a, &cfg, &in);
            TQ_CHECK(a.fan, "the fan dropped out inside the hysteresis band");
            if (tq_fails) break;
        }

        in.clt_k = cfg.fan_off_k - 0.5f;
        aux_update(&a, &cfg, &in);
        TQ_CHECK(!a.fan, "the fan stayed on below its off threshold");
        TQ_PASS("fan hysteresis");
    }

    TQ_CASE("the fan runs on after a hot shutdown, and stops");
    {
        /* A turbocharged engine keeps making heat after it stops: no
         * coolant flow and a turbine soaking back into the head. The
         * run-on is bounded because the other end of it is a flat
         * battery in the morning. */
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, cfg.fan_on_k + 2.0f);
        run_for(&a, &cfg, &in, 2.0f);
        TQ_CHECK(a.fan, "setup did not get the fan running");

        in.running = false;
        in.has_sync = false;
        in.rpm = 0.0f;
        f32 fan_s = 0.0f;
        for (u32 i = 0; i < 30000 && a.fan; i++) {   /* up to 300 s */
            aux_update(&a, &cfg, &in);
            if (a.fan) fan_s += in.dt;
        }
        TQ_CHECK(!a.fan, "the run-on never ended");
        TQ_NEAR(fan_s, cfg.fan_runon_s, 0.05f,
                "ran on for %.1f s, calibrated for %.1f", fan_s,
                cfg.fan_runon_s);
        TQ_PASS("bounded run-on");
    }

    TQ_CASE("a cooled engine ends the run-on early");
    {
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, cfg.fan_on_k + 2.0f);
        run_for(&a, &cfg, &in, 2.0f);

        in.running = false;
        in.clt_k = cfg.fan_off_k - 1.0f;
        aux_update(&a, &cfg, &in);
        TQ_CHECK(!a.fan, "the fan kept running on a cold engine");
        TQ_PASS("run-on ends on temperature");
    }

    TQ_CASE("the tacho reads what the cluster expects");
    {
        /* A four-cylinder cluster counts two sparks a crank
         * revolution. Getting this wrong does not break anything and
         * is immediately obvious to the driver, which is exactly why
         * it should be a calibration rather than a constant. */
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, 360.0f);
        aux_update(&a, &cfg, &in);
        TQ_NEAR(a.tacho_hz, 100.0f, 1e-3,
                "3000 rpm at two pulses per rev is 100 Hz, got %.1f",
                a.tacho_hz);
        TQ_NEAR(hal_host_sw_hz(HAL_SW_TACHO), a.tacho_hz, 1e-6,
                "the output did not get the frequency");

        in.rpm = 6000.0f;
        aux_update(&a, &cfg, &in);
        TQ_NEAR(a.tacho_hz, 200.0f, 1e-3, "not linear in rpm");

        in.rpm = 0.0f;
        aux_update(&a, &cfg, &in);
        TQ_NEAR(a.tacho_hz, 0.0f, 1e-6, "a stopped engine showed %.1f Hz",
                a.tacho_hz);

        aux_config_t six = cfg;
        six.tacho_pulses_per_rev = 3.0f;
        in.rpm = 3000.0f;
        aux_update(&a, &six, &in);
        TQ_NEAR(a.tacho_hz, 150.0f, 1e-3, "pulses per rev is not honoured");
        TQ_PASS("tacho");
    }

    TQ_CASE("the lamp follows the fault input");
    {
        aux_t a;
        aux_init(&a);
        aux_in_t in = running_at(3000.0f, 360.0f);
        aux_update(&a, &cfg, &in);
        TQ_CHECK(!a.mil, "the lamp is on with nothing wrong");
        TQ_CHECK(!hal_host_sw(HAL_SW_MIL), "the lamp output is on");

        in.faulted = true;
        aux_update(&a, &cfg, &in);
        TQ_CHECK(a.mil && hal_host_sw(HAL_SW_MIL), "the lamp did not light");

        in.faulted = false;
        aux_update(&a, &cfg, &in);
        TQ_CHECK(!a.mil, "the lamp latched on a cleared fault");
        TQ_PASS("lamp");
    }

    return tq_report("aux");
}
