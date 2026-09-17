#include "model.h"

#include <math.h>

tq_engine_t tq_engine_default(void)
{
    tq_engine_t e;
    e.n_cyl = 4;
    e.displacement_l = 2.0f;
    e.compression_ratio = 11.0f;
    e.afr_stoich = 14.7f;
    e.cf_a = 0.4f;
    e.cf_b = 0.005f;
    e.cf_c = 0.09f;
    e.cf_d = 0.0009f;
    e.stroke_m = 0.094f;
    return e;
}

f32 tq_vd_per_cyl_l(const tq_engine_t *e)
{
    return e->displacement_l / (f32)e->n_cyl;
}

f32 tq_air_mass(f32 ve, f32 map_kpa, f32 t_charge_k, const tq_engine_t *e)
{
    f32 rho = map_kpa / (TQ_R_AIR * t_charge_k);          /* kg/m^3 */
    return ve * tq_vd_per_cyl_l(e) * 1e-3f * rho * 1000.0f;
}

f32 tq_ve_from_air(f32 air_g, f32 map_kpa, f32 t_charge_k, const tq_engine_t *e)
{
    f32 rho = map_kpa / (TQ_R_AIR * t_charge_k);
    return air_g / (tq_vd_per_cyl_l(e) * 1e-3f * rho * 1000.0f);
}

f32 tq_spark_efficiency(f32 delta_from_mbt_deg)
{
    f32 d = tq_clampf(delta_from_mbt_deg, 0.0f, 60.0f);
    f32 eff = 1.0f - TQ_SPARK_EFF_K * powf(d, TQ_SPARK_EFF_P);
    return tq_clampf(eff, 0.0f, 1.0f);
}

f32 tq_lambda_efficiency(f32 lam)
{
    f32 d = lam - 0.88f;
    return tq_clampf(1.0f - 1.15f * d * d, 0.0f, 1.0f);
}

f32 tq_indicated_efficiency(const tq_engine_t *e)
{
    f32 ideal = 1.0f - powf(e->compression_ratio, -0.4f);
    return ideal * 0.62f;
}

f32 tq_base_torque(f32 air_g, f32 rpm, const tq_engine_t *e)
{
    (void)rpm;                       /* the closed form is speed-independent */
    f32 fuel_g = air_g / e->afr_stoich;
    f32 energy_j = fuel_g * 1e-3f * 44.0e6f;              /* LHV ~44 MJ/kg */
    f32 work_j = energy_j * tq_indicated_efficiency(e) * (f32)e->n_cyl;
    return work_j / (4.0f * TQ_PI);
}

f32 tq_friction_torque(f32 rpm, f32 map_kpa, const tq_engine_t *e)
{
    f32 sp = 2.0f * e->stroke_m * rpm / 60.0f;            /* piston speed m/s */
    f32 pmax = map_kpa * e->compression_ratio / 100.0f;
    f32 fmep_bar = e->cf_a + e->cf_b * pmax + e->cf_c * sp + e->cf_d * sp * sp;
    return fmep_bar * 1e5f * e->displacement_l * 1e-3f / (4.0f * TQ_PI);
}

f32 tq_brake_torque(f32 ve, f32 map_kpa, f32 t_charge_k, f32 rpm,
                    f32 spark, f32 mbt, f32 lam, const tq_engine_t *e)
{
    f32 air = tq_air_mass(ve, map_kpa, t_charge_k, e);
    f32 t_ind = tq_base_torque(air, rpm, e)
                * tq_spark_efficiency(mbt - spark)
                * tq_lambda_efficiency(lam);
    return t_ind - tq_friction_torque(rpm, map_kpa, e);
}

f32 tq_required_air(f32 torque_target, f32 rpm, f32 planned_spark, f32 mbt,
                    f32 lam, f32 map_kpa, const tq_engine_t *e)
{
    f32 needed = torque_target + tq_friction_torque(rpm, map_kpa, e);
    f32 eff = tq_spark_efficiency(mbt - planned_spark) * tq_lambda_efficiency(lam);
    if (eff < 1e-6f) {
        eff = 1e-6f;
    }
    f32 at_mbt = needed / eff;
    f32 work_j = at_mbt * 4.0f * TQ_PI;
    f32 energy_j = work_j / (tq_indicated_efficiency(e) * (f32)e->n_cyl);
    return energy_j / 44.0e6f * 1e3f * e->afr_stoich;
}

f32 tq_authority(f32 ve, f32 map_kpa, f32 t_charge_k, f32 rpm, f32 spark,
                 f32 mbt, f32 lam, const tq_engine_t *e)
{
    f32 now = tq_brake_torque(ve, map_kpa, t_charge_k, rpm, spark, mbt, lam, e);
    f32 floor_t = tq_brake_torque(ve, map_kpa, t_charge_k, rpm,
                                  mbt - 30.0f, mbt, lam, e);
    /* Not clamped: the reference does not clamp either, and a negative
     * value is meaningful -- it says spark is already below the floor the
     * authority is measured against. Callers decide what to do with it. */
    return now - floor_t;
}
