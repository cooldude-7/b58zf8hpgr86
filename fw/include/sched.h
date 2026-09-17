/* Angle-domain event scheduler.
 *
 * Spark and injection are decided in degrees and delivered in
 * microseconds. This module is the only place that conversion happens.
 *
 * The rule that makes it safe: an event is armed in hardware ahead of
 * time, and may be revised until the moment it starts. Once a coil is
 * charging, the start cannot be retracted -- only the firing point can
 * move, and only later, never earlier than the minimum dwell. Retracting
 * a started dwell is a misfire; firing early is a hole in a piston.
 */
#ifndef TQ_SCHED_H
#define TQ_SCHED_H

#include "decoder.h"
#include "hal.h"
#include "tq_types.h"

/* One injection event. A direct injection engine uses two or three per
 * cycle: a pilot early in the intake stroke for mixing, the main charge
 * behind it, and on a cold start a late one to put a rich cloud at the
 * plug. Port injection uses one and leaves the rest at zero. */
typedef struct {
    f32 soi_deg;           /* start of injection, degrees BTDC of its TDC */
    u32 pw_us;
} sched_pulse_t;

typedef struct {
    f32 tdc_deg;           /* this cylinder's firing TDC in the 720 frame */
    /* requested, in the angle domain */
    f32 spark_advance;     /* degrees BTDC */
    u32 dwell_us;
    sched_pulse_t pulse[HAL_MAX_PULSES];
    u8 n_pulses;
    bool spark_enabled;
    bool fuel_enabled;
    /* armed state */
    bool spark_armed;
    bool fuel_armed;
    tq_time_t spark_at;
    tq_time_t dwell_at;
} sched_cyl_t;

typedef struct {
    sched_cyl_t cyl[TQ_MAX_CYL];
    u8 n_cyl;
    u32 min_dwell_us;
    u32 max_dwell_us;
    /* How far ahead events are armed. Too short and a busy CPU misses
     * them; too long and every revision arrives after the arm. */
    f32 lookahead_deg;
    u32 spark_events;
    u32 fuel_events;
    u32 missed_events;
    u32 rejected_patterns;   /* injection sequences the hardware refused */
} sched_t;

void sched_init(sched_t *s, u8 n_cyl);

/* Firing order as TDC angles in the 720 frame. For an inline four that is
 * 0, 180, 360, 540 in firing order 1-3-4-2. */
void sched_set_tdc(sched_t *s, u8 cyl, f32 tdc_deg);

void sched_set_spark(sched_t *s, u8 cyl, f32 advance_deg, u32 dwell_us);
/* Single pulse: the simple case, and what port injection uses. */
void sched_set_injection(sched_t *s, u8 cyl, f32 soi_deg, u32 pw_us);

/* Two or three pulses, earliest first. Returns false if they do not fit
 * (out of order, overlapping, or too close for the injector's boost
 * supply to recover), in which case the previous set is kept: a
 * half-applied injection pattern is worse than an old one. */
bool sched_set_pulses(sched_t *s, u8 cyl, const sched_pulse_t *p, u8 n);

/* Global enables. Cutting fuel leaves the coils alone; cutting spark on a
 * running engine dumps raw fuel into the exhaust, so a torque cut uses
 * fuel, and spark is only cut with fuel already off. */
void sched_enable_spark(sched_t *s, bool on);
void sched_enable_fuel(sched_t *s, bool on);
void sched_cut_cylinder(sched_t *s, u8 cyl, bool spark_on, bool fuel_on);

/* Called from the tooth ISR after the decoder has been updated. Arms
 * whatever is now inside the lookahead window. */
void sched_update(sched_t *s, const decoder_t *d, tq_time_t now_us);

/* Called when sync is lost: everything armed is dropped. */
void sched_all_off(sched_t *s);

#endif /* TQ_SCHED_H */
