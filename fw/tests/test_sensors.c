/* The sensor layer: counts in, physical units out, and a considered
 * opinion about whether to believe them. */
#include <math.h>

#include "engine_rig.h"
#include "sensors.h"
#include "tq_test.h"

static void settle(sensors_t *s, int ms)
{
    for (int i = 0; i < ms; i++) sensors_update(s, 0.001f);
}

int main(void)
{
    sens_config_t cfg = sensors_config_default();

    TQ_CASE("a linear sensor round trips through counts");
    {
        sensors_t s; sensors_init(&s, &cfg);
        for (f32 kpa = 30.0f; kpa <= 250.0f; kpa += 55.0f) {
            hal_host_reset();
            rig_sensor(&cfg, HAL_ADC_MAP, kpa);
            sensors_init(&s, &cfg);
            settle(&s, 200);
            TQ_NEAR(sensors_value(&s, HAL_ADC_MAP), kpa, 1.0f,
                    "MAP round trip at %.0f", (double)kpa);
        }
        TQ_PASS("MAP converts both ways");
    }

    TQ_CASE("a thermistor round trips, which is not a linear fit");
    {
        /* Steinhart-Hart is a cubic in log resistance. If the inverse
         * used here and the forward conversion in the firmware ever
         * disagree, every temperature-indexed table silently indexes
         * the wrong row. */
        for (f32 k = 253.0f; k <= 393.0f; k += 35.0f) {
            hal_host_reset();
            sensors_t s; sensors_init(&s, &cfg);
            rig_sensor(&cfg, HAL_ADC_CLT, k);
            settle(&s, 8000);
            TQ_NEAR(sensors_value(&s, HAL_ADC_CLT), k, 2.0f,
                    "coolant round trip at %.0f K", (double)k);
        }
        TQ_PASS("NTC converts both ways");
    }

    TQ_CASE("a single spike is not a fault");
    {
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        rig_sensor(&cfg, HAL_ADC_MAP, 100.0f);
        settle(&s, 100);
        hal_host_set_adc(HAL_ADC_MAP, 4095u);     /* one bad sample */
        sensors_update(&s, 0.001f);
        TQ_CHECK(sensors_ok(&s, HAL_ADC_MAP),
                 "faulted the channel on one sample");
        TQ_PASS("spikes are debounced");
    }

    TQ_CASE("a stuck-high channel faults and serves its fallback");
    {
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        hal_host_set_adc(HAL_ADC_MAP, 4095u);     /* open circuit */
        settle(&s, 500);
        TQ_CHECK(!sensors_ok(&s, HAL_ADC_MAP), "never faulted");
        TQ_NEAR(sensors_value(&s, HAL_ADC_MAP), 101.3f, 0.1f,
                "did not serve the fallback");
        TQ_PASS("a failed sensor is disbelieved, not obeyed");
    }

    TQ_CASE("a coolant sensor fails HOT, never cold");
    {
        /* The direction matters more than the value. Falling back cold
         * would command warmup enrichment forever and wash the bores
         * with fuel; falling back hot merely loses the enrichment. */
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        hal_host_set_adc(HAL_ADC_CLT, 0u);        /* shorted */
        settle(&s, 500);
        TQ_CHECK(!sensors_ok(&s, HAL_ADC_CLT), "never faulted");
        TQ_CHECK(sensors_value(&s, HAL_ADC_CLT) > 340.0f,
                 "fell back to %.0f K, which is cold",
                 (double)sensors_value(&s, HAL_ADC_CLT));
        TQ_PASS("fails to the safe side");
    }

    TQ_CASE("oil pressure fails to ZERO, so the phaser gate closes");
    {
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        hal_host_set_adc(HAL_ADC_OIL_PRESSURE, 4095u);
        settle(&s, 500);
        TQ_CHECK(sensors_value(&s, HAL_ADC_OIL_PRESSURE) < 10.0f,
                 "a failed oil sensor reported pressure it cannot vouch for");
        TQ_PASS("no oil reading means no phaser authority");
    }

    TQ_CASE("a sensor that comes back is believed again");
    {
        /* Unlike a jumped timing chain, a loose connector that reseats
         * is a real and common thing and does not need a key cycle. */
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        hal_host_set_adc(HAL_ADC_MAP, 4095u);
        settle(&s, 500);
        TQ_CHECK(!sensors_ok(&s, HAL_ADC_MAP), "precondition");
        rig_sensor(&cfg, HAL_ADC_MAP, 100.0f);
        settle(&s, 500);
        TQ_CHECK(sensors_ok(&s, HAL_ADC_MAP), "stayed faulted after recovery");
        TQ_CHECK((s.fault_mask & (1u << HAL_ADC_MAP)) == 0u,
                 "the MAP fault bit was not cleared (mask 0x%X)",
                 s.fault_mask);
        TQ_PASS("recovers");
    }

    TQ_CASE("the filter is slower on coolant than on manifold pressure");
    {
        /* One time constant for every channel is wrong for most of them.
         * MAP has to keep up with the manifold emptying; coolant cannot
         * physically move fast, so anything fast on that line is noise. */
        hal_host_reset();
        sensors_t s; sensors_init(&s, &cfg);
        rig_sensor(&cfg, HAL_ADC_MAP, 100.0f);
        rig_sensor(&cfg, HAL_ADC_CLT, 300.0f);
        settle(&s, 5000);
        rig_sensor(&cfg, HAL_ADC_MAP, 200.0f);
        rig_sensor(&cfg, HAL_ADC_CLT, 380.0f);
        settle(&s, 30);
        f32 map_frac = (sensors_value(&s, HAL_ADC_MAP) - 100.0f) / 100.0f;
        f32 clt_frac = (sensors_value(&s, HAL_ADC_CLT) - 300.0f) / 80.0f;
        TQ_CHECK(map_frac > clt_frac + 0.5f,
                 "MAP moved %.2f and coolant %.2f in the same 30 ms",
                 (double)map_frac, (double)clt_frac);
        TQ_PASS("each channel is filtered for what it measures");
    }

    return tq_report("sensors");
}
