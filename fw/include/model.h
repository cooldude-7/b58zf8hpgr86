/* The torque model, ported from tqmodel/model.py.
 *
 * The Python is the reference and stays the reference: tests/golden.txt
 * is generated from it and fw/tests/test_model.c checks this code against
 * it. If the two disagree the C is wrong, not the Python.
 *
 * Single precision throughout, so the tolerance against the double
 * precision reference is 1e-4 relative, not exact equality.
 */
#ifndef TQ_MODEL_H
#define TQ_MODEL_H

#include "tq_types.h"

#define TQ_R_AIR 0.287f          /* kJ/(kg*K) */
/* Defined here rather than taken from math.h: M_PI is not in standard C
 * and is absent under -std=c11 on some toolchains. */
#define TQ_PI 3.14159265358979323846f
#define TQ_SPARK_EFF_K 1.096e-3f
#define TQ_SPARK_EFF_P 1.8f

typedef struct {
    u8 n_cyl;
    f32 displacement_l;
    f32 compression_ratio;
    f32 afr_stoich;
    f32 cf_a, cf_b, cf_c, cf_d;   /* Chen-Flynn */
    f32 stroke_m;
} tq_engine_t;

tq_engine_t tq_engine_default(void);

f32 tq_vd_per_cyl_l(const tq_engine_t *e);

/* Charge mass per cylinder per cycle, grams. */
f32 tq_air_mass(f32 ve, f32 map_kpa, f32 t_charge_k, const tq_engine_t *e);
f32 tq_ve_from_air(f32 air_g, f32 map_kpa, f32 t_charge_k, const tq_engine_t *e);

/* Torque as a fraction of MBT torque, given degrees retarded from MBT.
 * Zero slope at zero: MBT is the maximum by definition. */
f32 tq_spark_efficiency(f32 delta_from_mbt_deg);
f32 tq_lambda_efficiency(f32 lam);
f32 tq_indicated_efficiency(const tq_engine_t *e);

f32 tq_base_torque(f32 air_g, f32 rpm, const tq_engine_t *e);
f32 tq_friction_torque(f32 rpm, f32 map_kpa, const tq_engine_t *e);
f32 tq_brake_torque(f32 ve, f32 map_kpa, f32 t_charge_k, f32 rpm,
                    f32 spark, f32 mbt, f32 lam, const tq_engine_t *e);

/* The inverse: the charge mass that produces this torque at this spark. */
f32 tq_required_air(f32 torque_target, f32 rpm, f32 planned_spark, f32 mbt,
                    f32 lam, f32 map_kpa, const tq_engine_t *e);

/* How much torque the fast path can remove right now, without touching
 * air: the difference between what we make and what 30 degrees of retard
 * would leave. */
f32 tq_authority(f32 ve, f32 map_kpa, f32 t_charge_k, f32 rpm, f32 spark,
                 f32 mbt, f32 lam, const tq_engine_t *e);

#endif /* TQ_MODEL_H */
