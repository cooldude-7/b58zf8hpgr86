/* Drive-by-wire throttle, as two nested loops.
 *
 *   manifold pressure target  ->  [outer]  ->  throttle position command
 *   throttle position command ->  [inner]  ->  H-bridge duty
 *
 * Two loops rather than one because they answer different questions on
 * different timescales. The inner loop asks "is the plate where I put
 * it", and it is fast, mechanical and engine-independent. The outer asks
 * "is the manifold at the pressure the torque model wanted", and it is
 * slow, because filling a manifold takes tens of milliseconds and no
 * amount of gain makes air move sooner.
 *
 * Collapsing them into one loop is the tempting simplification and it
 * fails in a specific way: a single gain cannot be right for both a
 * plate that responds in 50 ms and a manifold that responds in 200 ms,
 * so it either hunts or crawls.
 *
 * Zero duty is NOT closed. A drive-by-wire plate has a return spring to
 * a limp-home position slightly open -- enough to idle and drive slowly
 * -- so that a dead ECU leaves the car moveable rather than stranded.
 * Opening the bridge is therefore a safe action, which is why the Level
 * 2 monitor's reaction is to do exactly that.
 */
#ifndef TQ_THROTTLE_H
#define TQ_THROTTLE_H

#include "tq_types.h"

typedef struct {
    /* Outer: manifold pressure to commanded plate position. */
    f32 kp_map;              /* percent of travel per kPa of error */
    f32 ki_map;
    f32 map_i_max;

    /* Inner: plate position to bridge duty. */
    f32 kp_pos;              /* duty per percent of position error */
    f32 ki_pos;
    f32 pos_i_max;

    f32 limp_pos_pct;        /* where the return spring holds it */
    f32 min_pos_pct, max_pos_pct;
    f32 disagree_pct;        /* TPS A vs B difference that is a fault */
} thr_config_t;

typedef struct {
    f32 cmd_pct;             /* commanded plate position: tps_cmd */
    f32 actual_pct;          /* what the sensors say */
    f32 duty;                /* what went to the bridge */
    f32 map_i, pos_i;
    bool plausible;          /* do the two TPS sensors agree? */
    bool enabled;
} throttle_t;

typedef struct {
    f32 dt;
    f32 map_target_kpa;
    f32 map_actual_kpa;
    f32 tps_a_pct, tps_b_pct;
    bool allow;              /* false: open the bridge, let the spring win */
} thr_in_t;

thr_config_t thr_config_default(void);
void throttle_init(throttle_t *t, const thr_config_t *cfg);
void throttle_update(throttle_t *t, const thr_config_t *cfg,
                     const thr_in_t *in);

#endif /* TQ_THROTTLE_H */
