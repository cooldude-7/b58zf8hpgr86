/* Wastegate and boost control.
 *
 * The B48's wastegate is a MOTOR with a position sensor, not a pneumatic
 * can with a spring. So it gets the same treatment as the throttle: an
 * outer loop that asks for a manifold pressure and an inner loop that
 * puts the gate where the outer loop wanted. That is also why swapping
 * to a turbo with a pneumatic actuator is not a bolt-on -- the control
 * problem changes shape, from position control to duty control on a
 * solenoid.
 *
 * Boost is not a separate request. The torque path already produced a
 * manifold pressure target; above atmospheric the throttle cannot reach
 * it alone and the wastegate has to close. Treating boost as its own
 * target, indexed by rpm the way most aftermarket ECUs do, is what makes
 * boost and throttle fight each other on a torque-structured engine.
 *
 * LIFT-OFF is a calibration, not a side effect. When the driver lifts,
 * holding the gate SHUT keeps the turbo spinning against a closed
 * throttle, which is what produces compressor surge -- the "stututu".
 * Opening it lets the turbine slow and the boost bleed away quietly.
 * Both are legitimate; which one you get should be a decision in a
 * table rather than an accident of how the controller was written.
 */
#ifndef TQ_BOOST_H
#define TQ_BOOST_H

#include "tq_types.h"

typedef struct {
    /* Outer: pressure error to commanded gate position. Position is
     * 0 % = fully CLOSED (all gas through the turbine, maximum boost)
     * and 100 % = fully open. */
    f32 kp_map, ki_map;
    f32 map_i_max;

    /* Inner: gate position to bridge duty. */
    f32 kp_pos, ki_pos;
    f32 pos_i_max;

    f32 open_pct;            /* where it sits with no demand */
    f32 overboost_kpa;       /* above this, drive it open regardless */

    /* Lift-off. */
    f32 lift_tps_pct;        /* below this throttle counts as a lift */
    f32 lift_hold_pct;       /* where to hold the gate during one */
    f32 lift_hold_s;         /* for how long */
} boost_config_t;

typedef struct {
    f32 cmd_pct;             /* commanded gate position */
    f32 actual_pct;
    f32 duty;
    f32 map_i, pos_i;
    bool lifting;
    bool lift_armed;         /* a lift is only armed by throttle being applied */
    f32 lift_t;
    bool enabled;
} boost_t;

typedef struct {
    f32 dt;
    f32 map_target_kpa;      /* from the torque path, not a boost table */
    f32 map_actual_kpa;
    f32 gate_pct;            /* measured position */
    f32 tps_pct;
    bool running;
    bool sensor_ok;
} boost_in_t;

boost_config_t boost_config_default(void);
void boost_init(boost_t *b, const boost_config_t *cfg);
void boost_update(boost_t *b, const boost_config_t *cfg, const boost_in_t *in);

#endif /* TQ_BOOST_H */
