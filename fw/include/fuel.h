/* Fuel path: charge mass to injector pulse width, and the high pressure
 * pump loop that makes the pulse width mean anything.
 *
 * Direct injection couples these two: pulse width is computed from rail
 * pressure, and rail pressure is controlled by a valve timed against the
 * pump lobes, which needs cam phase. Neither works without the decoder.
 */
#ifndef TQ_FUEL_H
#define TQ_FUEL_H

#include "model.h"
#include "tq_types.h"

#define TQ_FUEL_DENSITY_G_CC 0.745f      /* petrol at 15 C */

/* How many breakpoints the short-pulse correction carries. Small,
 * because the region it describes is small: everything above a
 * millisecond or so is linear and needs no table at all. */
#define TQ_SMALL_PW_N 6

typedef struct {
    f32 flow_cc_min;         /* static flow at rated pressure */
    f32 rated_dp_kpa;        /* the pressure drop that rating was taken at */
    f32 deadtime_ms;         /* at 13.8 V */
    f32 deadtime_slope_ms_v; /* how dead time grows as voltage falls */
    f32 min_pulse_ms;        /* below this the injector is not linear */

    /* Short-pulse correction. Near the bottom of its range an injector
     * does not fully open, so a 0.4 ms command delivers proportionally
     * far less fuel than a 4 ms one. Without this the engine is lean at
     * idle and cruise while being perfectly calibrated at load -- which
     * reads as a VE table problem, sends the tuner off to fix the wrong
     * surface, and stays wrong.
     *
     * Additive microseconds, interpolated between breakpoints, zero
     * above the last one. These come from a flow bench, not a guess. */
    f32 small_pw_us[TQ_SMALL_PW_N];    /* ascending commanded widths */
    f32 small_add_us[TQ_SMALL_PW_N];   /* what to add at each */
} tq_injector_t;

/* Coil dwell against supply voltage.
 *
 * Charge time to reach a given coil current depends on supply voltage,
 * so a fixed dwell undercharges the coil exactly when the battery is
 * lowest -- during cranking, which is when a good spark matters most and
 * when a weak one reads as "it just will not start". Lives here with the
 * injector dead-time compensation because it is the same idea: what an
 * actuator needs in order to do the same thing at a different voltage. */
#define TQ_DWELL_N 5

typedef struct {
    f32 volts[TQ_DWELL_N];   /* ascending */
    f32 dwell_ms[TQ_DWELL_N];
} tq_dwell_t;

tq_dwell_t tq_dwell_default(void);
u32 tq_dwell_us(const tq_dwell_t *d, f32 battery_v);

tq_injector_t tq_injector_default(void);

/* Fuel mass for a charge, in grams. */
f32 tq_fuel_mass(f32 air_g, f32 lambda_target, const tq_engine_t *e);

/* Pulse width in microseconds. Flow scales with the square root of the
 * pressure drop across the nozzle, so a rail pressure error becomes a
 * fuelling error unless it is compensated here. */
u32 tq_pulse_width_us(f32 fuel_g, f32 rail_kpa, f32 cylinder_kpa,
                      f32 battery_v, const tq_injector_t *inj);

/* The commanded width after the short-pulse correction. Applied inside
 * tq_pulse_width_us; exposed so a test and a tuner can see the size of
 * the correction rather than only its effect. */
u32 tq_small_pulse_us(u32 pw_us, const tq_injector_t *inj);

/* Duty against the crank window injection can actually use, not against
 * the whole cycle. Measuring a direct injector against 720 degrees makes
 * it look about three times larger than it is. */
f32 tq_injector_duty(u32 pw_us, f32 rpm, f32 window_deg);

/* ---- high pressure pump --------------------------------------------- */
typedef struct {
    f32 target_kpa;
    f32 kp, ki;
    f32 integral;
    f32 duty;                /* 0..1 of a pump lobe's spill window */
    f32 lobes_per_cycle;
    bool enabled;
} tq_hpfp_t;

void tq_hpfp_init(tq_hpfp_t *h, f32 lobes_per_cycle);

/* Run the loop. `demand_g_per_cycle` feeds forward what the injectors are
 * about to take, so the loop is not asked to discover it from the error.
 * Returns the spill-valve close fraction, 0..1. */
f32 tq_hpfp_update(tq_hpfp_t *h, f32 dt_s, f32 measured_kpa,
                   f32 demand_g_per_cycle);

/* Where the pump's lobes sit, and how the duty becomes an angle.
 *
 * The pump is driven off a cam lobe, so it delivers in discrete strokes
 * rather than continuously. A spill valve holds the chamber open to the
 * low pressure side; closing it part way through a stroke is what sends
 * fuel to the rail, and the later it closes the less goes. That makes
 * pump control an angle-domain problem, which is why it needs the
 * decoder and why it cannot be done with a plain PWM output.
 */
typedef struct {
    f32 lobes_per_cycle;   /* three on a B48: cam lobes per 720 crank deg */
    f32 first_lobe_deg;    /* crank angle where the first stroke begins */
    f32 lobe_span_deg;     /* crank angle the pumping stroke covers */
    u32 valve_hold_us;     /* how long the valve is energised to close it */
} tq_hpfp_sched_t;

tq_hpfp_sched_t tq_hpfp_sched_default(void);

/* The crank angle at which the valve must close to deliver `duty` of a
 * full stroke, for the next lobe at or after `after_deg`. Returns false
 * when the duty is too low to be worth a stroke at all. */
bool tq_hpfp_close_angle(const tq_hpfp_sched_t *cfg, f32 duty,
                         f32 after_deg, f32 *close_deg);

#endif /* TQ_FUEL_H */
