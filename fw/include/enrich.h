/* Fuel corrections that are about TIME rather than about steady state.
 *
 * The speed-density model says how much air is in the cylinder. It does
 * not say how much of the injected fuel will actually be there to burn,
 * and on a cold or rapidly changing engine those are very different
 * numbers. Everything here multiplies the base fuel mass.
 *
 * This is the gap between "runs on a dyno at 3000 rpm" and "is a car".
 * A model-only ECU makes perfect steady-state power and cannot start on
 * a winter morning, cannot idle, and stumbles every time the throttle
 * moves -- because all three are transient behaviour and none of them
 * follow from the steady-state physics.
 *
 *   CRANKING     a large multiplier while the starter is turning it,
 *                because most of what is injected condenses on cold
 *                port and cylinder walls instead of burning.
 *   AFTER-START  a decaying extra over the first few seconds after it
 *                catches, without which it fires once and dies.
 *   WARMUP       a coolant-indexed multiplier tapering to 1.0.
 *   ACCELERATION a correction for the fuel film that has not caught up
 *                with a fast throttle opening.
 *   DECEL CUT    fuel off entirely on a closed throttle at speed.
 */
#ifndef TQ_ENRICH_H
#define TQ_ENRICH_H

#include "tq_types.h"

#define ENR_CLT_N 6

typedef struct {
    /* Cranking and warmup, both indexed by coolant temperature. */
    f32 clt_k[ENR_CLT_N];              /* ascending, shared axis */
    f32 crank_mult[ENR_CLT_N];
    f32 warm_mult[ENR_CLT_N];

    /* After-start: an extra fraction on top of warmup, decaying away. */
    f32 astart_extra;                  /* 0.4 = 40 % extra at the moment it fires */
    f32 astart_tau_s;

    /* Acceleration. Driven by rate of change of manifold pressure,
     * because that is what actually tells you the charge is growing --
     * throttle rate does not, on a boosted engine where the manifold can
     * fill without the throttle moving at all. */
    f32 accel_gain;                    /* fraction per kPa/s */
    f32 accel_tau_s;
    f32 accel_max;
    f32 accel_cold_scale;              /* how much worse it is when cold */

    /* Deceleration fuel cut. */
    f32 dfco_rpm;                      /* cut above this... */
    f32 dfco_tps_pct;                  /* ...with the throttle under this */
    f32 dfco_resume_rpm;               /* resume below this: hysteresis */
    f32 dfco_clt_min_k;                /* never while the engine is cold */
} enr_config_t;

typedef struct {
    f32 crank, astart, warm, accel;    /* each correction, for logging */
    f32 total;                         /* their product */
    bool fuel_cut;                     /* decel cut is on */

    f32 astart_t;                      /* seconds since it caught */
    f32 accel_state;
    f32 map_prev;
    bool have_prev;
    bool was_cranking;
} enrich_t;

typedef struct {
    f32 dt;
    f32 rpm;
    f32 clt_k;
    f32 map_kpa;
    f32 tps_pct;
    bool cranking;
    bool running;
} enr_in_t;

enr_config_t enr_config_default(void);
void enrich_init(enrich_t *e);
void enrich_update(enrich_t *e, const enr_config_t *cfg, const enr_in_t *in);

#endif /* TQ_ENRICH_H */
