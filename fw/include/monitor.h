/* Level 2 torque monitor, ported from tuner/core/monitor.py.
 *
 * Kept behaviourally identical to the Python so the tests written against
 * one apply to the other. See that file for why each threshold exists.
 */
#ifndef TQ_MONITOR_H
#define TQ_MONITOR_H

#include "tq_types.h"

typedef enum { MON_OK = 0, MON_REDUCED, MON_IDLE_ONLY, MON_SHUTDOWN } mon_limp_t;

enum {
    MON_F_NONE = 0,
    MON_F_PEDAL_PLAUSIBILITY = 1,
    MON_F_TPS_PLAUSIBILITY = 2,
    MON_F_TORQUE_EXCEEDS_PERMISSIBLE = 3,
    MON_F_TPS_TRACKING = 4,
    MON_F_OVERSPEED = 5,
    MON_F_OVERBOOST = 6
};

#define MON_PEDAL_DISAGREE_PCT 10.0f
#define MON_TPS_DISAGREE_PCT 8.0f
#define MON_TPS_TRACKING_PCT 15.0f
#define MON_DEBOUNCE_S 0.10f
#define MON_TORQUE_MARGIN_NM 30.0f
#define MON_TORQUE_DEBOUNCE_S 0.20f

typedef struct {
    mon_limp_t limp;
    u8 fault;                 /* the FIRST fault seen: the root cause */
    u16 fault_mask;           /* every fault, as a bit per code */
    f32 permissible;
    f32 t_pedal, t_tps, t_track, t_torque;
} tq_monitor_t;

typedef struct {
    f32 dt;
    f32 pedal_a, pedal_b;
    f32 tps_a, tps_b, tps_cmd;
    f32 torque, rpm, max_torque;
    f32 rev_limit, map_kpa, overboost_kpa;
} mon_inputs_t;

void tq_monitor_reset(tq_monitor_t *m);
mon_limp_t tq_monitor_update(tq_monitor_t *m, const mon_inputs_t *in);
f32 tq_monitor_torque_cap(const tq_monitor_t *m, f32 max_torque);

#endif /* TQ_MONITOR_H */
