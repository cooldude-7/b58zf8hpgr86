/* Closed-loop fuel: the feedback the open-loop model does not have.
 *
 * Before this, lambda_meas was read only by the torque model -- to work
 * out how mixture affected torque -- and never corrected fuelling at
 * all. tq_fuel_mass() took the TARGET and nothing else, so the VE table
 * was never corrected by what the sensor actually read and any VE error,
 * or an injector 5 % off its rating, persisted forever.
 *
 * Two trims, and the difference between them is the point:
 *
 *   SHORT TERM is a fast PI on the measured-versus-target error. It
 *   reacts within a breath and it forgets. It is what handles a gust of
 *   fuel pressure or a momentarily wrong VE cell.
 *
 *   LONG TERM is what the short term settles to, learned per operating
 *   region and remembered. It is what handles the injector that is
 *   permanently 5 % small, so that the next time the engine visits that
 *   region it starts from the right number instead of re-discovering the
 *   same correction from scratch.
 *
 * An ECU with only the short term re-learns constantly and is lean for a
 * moment every time conditions change. One with only the long term
 * cannot react at all.
 *
 * Note what this deliberately IS, relative to the teaching product in
 * this same repository: it is autotune. Lambda One withholds it on
 * purpose, because a student who presses a button has learned which
 * button to press. An engine has no such need.
 */
#ifndef TQ_LAMBDA_H
#define TQ_LAMBDA_H

#include "tq_types.h"

#define LAM_RPM_N 4
#define LAM_LOAD_N 4

typedef struct {
    f32 kp, ki;
    f32 short_max;            /* authority, 0.25 = +/- 25 % */
    f32 long_max;
    f32 learn_tau_s;          /* how fast short term bleeds into long */
    f32 min_clt_k;            /* no closed loop on a cold engine */
    f32 settle_s;             /* exhaust transport delay before believing it */
    f32 target_band;          /* |target - 1| above this is deliberate, so open loop */
    f32 total_max;            /* ceiling on the PRODUCT of both trims */
    f32 rpm_break[LAM_RPM_N];
    f32 load_break[LAM_LOAD_N];
} lam_config_t;

typedef struct {
    f32 short_trim;           /* multiplier, 1.0 = no correction */
    f32 long_trim[LAM_LOAD_N][LAM_RPM_N];
    f32 total;                /* what to multiply fuel mass by */
    bool closed;              /* is the loop actually running */
    f32 integ;
    u8 cell_r, cell_l;
    f32 dwell_s;              /* how long in this cell */
} lambda_t;

typedef struct {
    f32 dt;
    f32 lambda_meas, lambda_target;
    f32 rpm, load_kpa, clt_k;
    bool sensor_ok;
    bool inhibit;             /* fuel cut, cranking, or a transient */
} lam_in_t;

lam_config_t lam_config_default(void);
void lambda_init(lambda_t *l, const lam_config_t *cfg);
void lambda_update(lambda_t *l, const lam_config_t *cfg, const lam_in_t *in);

#endif /* TQ_LAMBDA_H */
