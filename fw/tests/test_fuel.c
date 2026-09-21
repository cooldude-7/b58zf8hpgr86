/* Fuel path and pump loop. */
#include <math.h>

#include "fuel.h"
#include "tq_test.h"

int main(void)
{
    tq_engine_t e = tq_engine_default();
    tq_injector_t inj = tq_injector_default();

    TQ_CASE("fuel mass follows air and lambda");
    {
        f32 f1 = tq_fuel_mass(0.5f, 1.0f, &e);
        TQ_NEAR(f1, 0.5f / 14.7f, 1e-6, "stoich fuel for 0.5 g of air");
        f32 rich = tq_fuel_mass(0.5f, 0.8f, &e);
        TQ_CHECK(rich > f1, "lambda 0.8 should need more fuel than 1.0");
        TQ_NEAR(rich, f1 / 0.8f, 1e-6, "rich scaling");
        TQ_PASS("fuel mass");
    }

    TQ_CASE("pulse width falls as rail pressure rises");
    {
        /* pressure DROP of 2500 and 10000 kPa: exactly four times, which
         * under a square-root flow law should halve the open time.
         *
         * A deliberately large charge, so both pulses land well clear of
         * the short-pulse correction region. That correction is real and
         * is tested on its own below; mixing it in here would be testing
         * two things at once and concluding nothing about either. */
        u32 low = tq_pulse_width_us(0.30f, 3000.0f, 500.0f, 13.8f, &inj);
        u32 high = tq_pulse_width_us(0.30f, 10500.0f, 500.0f, 13.8f, &inj);
        TQ_CHECK(high < low, "more pressure should need less time (%u vs %u)",
                 high, low);
        f32 dead = inj.deadtime_ms * 1000.0f;
        TQ_NEAR(((f32)high - dead) * 2.0f, ((f32)low - dead), (f32)low * 0.02f,
                "sqrt law");
        TQ_PASS("rail pressure compensation");
    }

    TQ_CASE("short pulses are corrected, long ones are left alone");
    {
        /* Near the bottom of its range an injector does not fully open,
         * so a short command delivers proportionally less fuel. Without
         * this the engine is lean at idle and cruise while perfectly
         * calibrated at load -- which reads as a VE problem and sends
         * the tuner to fix the wrong surface. */
        u32 tiny = tq_small_pulse_us(400u, &inj);
        u32 mid = tq_small_pulse_us(1400u, &inj);
        u32 big = tq_small_pulse_us(6000u, &inj);
        TQ_CHECK(tiny > 400u, "a 400 us command got no correction");
        TQ_CHECK(mid > 1400u, "a 1400 us command got no correction");
        TQ_CHECK(big == 6000u, "a 6 ms command was corrected (%u)", big);
        TQ_CHECK((tiny - 400u) > (mid - 1400u),
                 "the correction should grow as the pulse shrinks "
                 "(%u vs %u)", tiny - 400u, mid - 1400u);
        TQ_CHECK(tq_small_pulse_us(0u, &inj) == 0u,
                 "corrected a zero pulse into a real one, which would "
                 "inject fuel during a fuel cut");
        TQ_PASS("short-pulse nonlinearity");
    }

    TQ_CASE("dwell grows as the battery falls");
    {
        /* The failure this prevents is specific: a fixed dwell
         * undercharges the coil during cranking, which is exactly when
         * the battery is lowest and when a weak spark reads as "it just
         * will not start". */
        tq_dwell_t d = tq_dwell_default();
        u32 cranking = tq_dwell_us(&d, 9.0f);
        u32 running = tq_dwell_us(&d, 14.0f);
        TQ_CHECK(cranking > running,
                 "cranking dwell %u us is not longer than running %u us",
                 cranking, running);
        TQ_CHECK(cranking > running * 3u / 2u,
                 "the compensation is too small to matter (%u vs %u)",
                 cranking, running);
        /* Flat outside the table rather than extrapolating off a cliff. */
        TQ_CHECK(tq_dwell_us(&d, 2.0f) == tq_dwell_us(&d, 8.0f),
                 "extrapolated below the table");
        TQ_CHECK(tq_dwell_us(&d, 30.0f) == tq_dwell_us(&d, 16.0f),
                 "extrapolated above the table");
        TQ_PASS("dwell voltage compensation");
    }

    TQ_CASE("cylinder pressure is subtracted, not ignored");
    {
        u32 vac = tq_pulse_width_us(0.03f, 8000.0f, 30.0f, 13.8f, &inj);
        u32 boost = tq_pulse_width_us(0.03f, 8000.0f, 4000.0f, 13.8f, &inj);
        TQ_CHECK(boost > vac, "a pressurised cylinder needs a longer pulse");
        TQ_PASS("differential pressure");
    }

    TQ_CASE("dead time grows as the battery falls");
    {
        u32 good = tq_pulse_width_us(0.03f, 8000.0f, 500.0f, 13.8f, &inj);
        u32 weak = tq_pulse_width_us(0.03f, 8000.0f, 500.0f, 10.0f, &inj);
        TQ_CHECK(weak > good, "low voltage should lengthen the pulse");
        TQ_NEAR((f32)(weak - good), 3.8f * 90.0f, 20.0f, "dead time slope");
        TQ_PASS("voltage compensation");
    }

    TQ_CASE("a pulse below the linear region is refused");
    {
        TQ_CHECK(tq_pulse_width_us(1e-6f, 8000.0f, 500.0f, 13.8f, &inj) == 0,
                 "an unpredictably small pulse was commanded");
        TQ_CHECK(tq_pulse_width_us(0.0f, 8000.0f, 500.0f, 13.8f, &inj) == 0,
                 "zero fuel produced a pulse");
        TQ_PASS("minimum pulse honoured");
    }

    TQ_CASE("a collapsed rail does not divide by zero");
    {
        u32 pw = tq_pulse_width_us(0.03f, 100.0f, 2000.0f, 13.8f, &inj);
        TQ_CHECK(pw > 0 && pw < 1000000u, "pw %u with the rail below the cylinder", pw);
        TQ_PASS("no divide by zero");
    }

    TQ_CASE("duty cycle is bounded");
    {
        /* 240 crank degrees at 7500 rpm is 5.33 ms of usable window */
        TQ_NEAR(tq_injector_duty(2667, 7500.0f, 240.0f), 50.0f, 1.0f,
                "2.67 ms into a 5.33 ms window");
        TQ_CHECK(tq_injector_duty(100000, 7500.0f, 240.0f) <= 100.0f, "duty over 100%%");
        TQ_CHECK(tq_injector_duty(5000, 0.0f, 240.0f) == 0.0f, "duty at zero rpm");
        TQ_CHECK(tq_injector_duty(2667, 7500.0f, 240.0f)
                 > tq_injector_duty(2667, 7500.0f, 720.0f),
                 "a narrower window must show a higher duty");
        TQ_PASS("duty");
    }

    TQ_CASE("the pump loop reaches its target");
    {
        tq_hpfp_t h;
        tq_hpfp_init(&h, 3.0f);
        h.enabled = true;
        h.target_kpa = 8000.0f;
        f32 rail = 500.0f;
        for (int i = 0; i < 4000; i++) {
            f32 duty = tq_hpfp_update(&h, 0.001f, rail, 0.02f);
            /* a crude rail: the pump adds, the injectors take */
            rail += (duty * 9000.0f - 0.02f * 12000.0f - (rail - 500.0f) * 0.4f)
                    * 0.001f;
        }
        TQ_NEAR(rail, 8000.0f, 400.0f, "rail settled at %.0f kPa", rail);
        TQ_PASS("pump loop converges");
    }

    TQ_CASE("the pump loop does not wind up while disabled");
    {
        tq_hpfp_t h;
        tq_hpfp_init(&h, 3.0f);
        h.enabled = false;
        for (int i = 0; i < 1000; i++) {
            tq_hpfp_update(&h, 0.001f, 300.0f, 0.02f);
        }
        TQ_NEAR(h.integral, 0.0f, 1e-9, "integral wound up with the pump off");
        h.enabled = true;
        f32 d = tq_hpfp_update(&h, 0.001f, 300.0f, 0.0f);
        TQ_CHECK(d <= 1.0f && d >= 0.0f, "duty %f out of range", (double)d);
        TQ_PASS("no windup");
    }

    TQ_CASE("duty stays in range under a huge error");
    {
        tq_hpfp_t h;
        tq_hpfp_init(&h, 3.0f);
        h.enabled = true;
        h.target_kpa = 20000.0f;
        for (int i = 0; i < 5000; i++) {
            f32 d = tq_hpfp_update(&h, 0.001f, 200.0f, 0.05f);
            TQ_CHECK(d >= 0.0f && d <= 1.0f, "duty %f", (double)d);
            if (tq_fails) break;
        }
        TQ_PASS("duty bounded");
    }

    return tq_report("fuel");
}
