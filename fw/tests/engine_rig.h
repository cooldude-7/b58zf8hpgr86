/* Shared bench-rig helpers: feed the ECU through its real input paths.
 *
 * The temptation in a test is to write ecu.sig.map_kpa directly. That
 * skips the sensor layer entirely, so a wrong conversion, a wrong
 * plausibility range and a wrong fallback all pass. These helpers set
 * the ADC counts a real sensor would produce instead, so the test
 * exercises the path the engine will.
 */
#ifndef ENGINE_RIG_H
#define ENGINE_RIG_H

#include "hal_host.h"
#include "sensors.h"
#include "throttle.h"

/* Say "the coolant is at 363 K" and let the conversion run. */
static inline void rig_sensor(const sens_config_t *cfg, hal_adc_t ch, f32 value)
{
    hal_host_set_adc(ch, sensors_counts_for(cfg, ch, value));
}

/* A plausible set of running-engine readings. */
static inline void rig_sensors_running(const sens_config_t *cfg, f32 map_kpa,
                                       f32 pedal_pct, f32 tps_pct)
{
    rig_sensor(cfg, HAL_ADC_MAP, map_kpa);
    rig_sensor(cfg, HAL_ADC_IAT, 298.0f);
    rig_sensor(cfg, HAL_ADC_CLT, 363.0f);
    rig_sensor(cfg, HAL_ADC_LAMBDA, 1.0f);
    rig_sensor(cfg, HAL_ADC_RAIL_PRESSURE, 8000.0f);
    rig_sensor(cfg, HAL_ADC_BATTERY, 13.8f);
    rig_sensor(cfg, HAL_ADC_OIL_PRESSURE, 350.0f);
    rig_sensor(cfg, HAL_ADC_PEDAL_A, pedal_pct);
    rig_sensor(cfg, HAL_ADC_PEDAL_B, pedal_pct);
    rig_sensor(cfg, HAL_ADC_TPS_A, tps_pct);
    rig_sensor(cfg, HAL_ADC_TPS_B, tps_pct);
}

/* A throttle plate with a return spring, so the position loop has
 * something to act on. Without a plant the commanded position and the
 * measured position diverge forever, and the Level 2 tracking check
 * fires on a fault the test never injected. */
typedef struct {
    f32 pos_pct;
    f32 rate_pct_s;     /* travel rate at full duty */
    f32 spring_pct;     /* where it goes with the bridge open */
    bool seized;
} thr_plant_t;

static inline void thr_plant_init(thr_plant_t *p, f32 spring_pct)
{
    p->pos_pct = spring_pct;
    p->rate_pct_s = 400.0f;
    p->spring_pct = spring_pct;
    p->seized = false;
}

static inline void thr_plant_step(thr_plant_t *p, f32 duty, bool enabled,
                                  f32 dt)
{
    if (p->seized) return;
    if (!enabled) {
        /* Bridge open: the spring wins, quickly. */
        f32 k = dt / 0.08f;
        if (k > 1.0f) k = 1.0f;
        p->pos_pct += (p->spring_pct - p->pos_pct) * k;
        return;
    }
    p->pos_pct += duty * p->rate_pct_s * dt;
    p->pos_pct = tq_clampf(p->pos_pct, 0.0f, 100.0f);
}

#endif /* ENGINE_RIG_H */
