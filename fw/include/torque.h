/* The torque path: pedal to a number of newton-metres, and back out to
 * what the air has to do.
 *
 * This is the claim the whole project rests on, and until now it was the
 * one thing not actually wired. tq_required_air() -- the inverse model --
 * existed in model.c and was called from nowhere, and ecu_signals_t's
 * torque_request was read by the Level 2 monitor and written by nothing.
 * That second one mattered: the monitor's ceiling fell back to a fixed
 * 400 Nm, so the permissible-torque check, which is the entire point of
 * Level 2, was comparing against a constant instead of against what the
 * driver had asked for.
 *
 * The structure, in order:
 *
 *   pedal  -> driver torque request      (a pedal map, not a throttle map)
 *   idle   -> idle torque request        (a PI loop on rpm error)
 *   others -> arbitration                (shift cut, traction, limits)
 *          -> ONE target
 *          -> inverse model              (how much air makes that torque)
 *          -> a manifold pressure target (what the throttle must achieve)
 *
 * Everything that wants to influence the engine asks in the same
 * currency, which is what makes coordinating them possible at all. A
 * shift cut and an idle controller fighting over throttle position is
 * incoherent; the same two asking for torque is arithmetic.
 */
#ifndef TQ_TORQUE_H
#define TQ_TORQUE_H

#include "model.h"
#include "tq_types.h"

typedef struct {
    f32 max_torque_nm;       /* what this engine can make, for scaling */
    f32 pedal_gamma;         /* >1 softens the first part of the travel */

    /* Idle. The target moves with coolant because a cold engine needs
     * more speed to stay alight, and because a fast idle warms the
     * catalyst sooner. */
    f32 idle_rpm_cold, idle_rpm_hot;
    f32 idle_clt_cold_k, idle_clt_hot_k;
    f32 idle_kp, idle_ki;
    f32 idle_max_nm;         /* how much torque idle may ask for */
    f32 idle_band_rpm;       /* above target + this, idle asks for nothing */
} tq_coord_config_t;

typedef struct {
    f32 pedal_pct;
    f32 rpm;
    f32 clt_k;
    f32 ve, map_kpa, iat_k;
    f32 spark_deg, mbt_deg, lambda;
    bool running;
    f32 dt;
    /* Torque ceiling from anything that limits: the Level 2 monitor, a
     * shift cut, traction. Negative means "no limit". */
    f32 limit_nm;
} tq_coord_in_t;

typedef struct {
    f32 driver_nm;
    f32 idle_nm;
    f32 target_nm;           /* after arbitration and limits */
    f32 idle_target_rpm;
    f32 idle_i;              /* the idle integrator */
    f32 air_target_g;        /* from the inverse model */
    f32 map_target_kpa;      /* what the throttle has to achieve */
} tq_coord_t;

tq_coord_config_t tq_coord_config_default(void);
void tq_coord_init(tq_coord_t *c, const tq_coord_config_t *cfg);
void tq_coord_update(tq_coord_t *c, const tq_coord_config_t *cfg,
                     const tq_coord_in_t *in, const tq_engine_t *e);

#endif /* TQ_TORQUE_H */
