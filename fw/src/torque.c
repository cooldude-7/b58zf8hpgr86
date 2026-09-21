#include "torque.h"

tq_coord_config_t tq_coord_config_default(void)
{
    tq_coord_config_t c;
    c.max_torque_nm = 400.0f;
    /* A linear pedal feels darty off idle, because torque is not linear
     * in throttle and the first few percent of travel move a lot of air.
     * Squaring it gives the bottom of the travel resolution and keeps
     * full pedal meaning full torque. */
    c.pedal_gamma = 1.8f;

    c.idle_rpm_cold = 1200.0f;
    c.idle_rpm_hot = 750.0f;
    c.idle_clt_cold_k = 253.0f;     /* -20 C */
    c.idle_clt_hot_k = 353.0f;      /* +80 C */
    c.idle_kp = 0.08f;              /* Nm per rpm of error */
    c.idle_ki = 0.25f;              /* Nm per rpm-second */
    c.idle_max_nm = 60.0f;
    c.idle_band_rpm = 400.0f;
    return c;
}

void tq_coord_init(tq_coord_t *c, const tq_coord_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*c); i++) {
        ((u8 *)c)[i] = 0;
    }
    c->idle_target_rpm = cfg->idle_rpm_hot;
}

/* Interpolate the idle target between the cold and hot anchors. */
static f32 idle_target(const tq_coord_config_t *cfg, f32 clt_k)
{
    f32 span = cfg->idle_clt_hot_k - cfg->idle_clt_cold_k;
    if (span < 1.0f) return cfg->idle_rpm_hot;
    f32 f = (clt_k - cfg->idle_clt_cold_k) / span;
    f = tq_clampf(f, 0.0f, 1.0f);
    return cfg->idle_rpm_cold + (cfg->idle_rpm_hot - cfg->idle_rpm_cold) * f;
}

void tq_coord_update(tq_coord_t *c, const tq_coord_config_t *cfg,
                     const tq_coord_in_t *in, const tq_engine_t *e)
{
    /* ---- what the driver is asking for ------------------------------ */
    f32 p = tq_clampf(in->pedal_pct, 0.0f, 100.0f) / 100.0f;
    f32 shaped = p;
    for (f32 g = cfg->pedal_gamma; g > 1.0f; g -= 1.0f) {
        shaped *= (g >= 2.0f) ? p : (1.0f + (p - 1.0f) * (g - 1.0f));
    }
    c->driver_nm = shaped * cfg->max_torque_nm;

    /* ---- what idle is asking for ------------------------------------ */
    c->idle_target_rpm = idle_target(cfg, in->clt_k);
    f32 err = c->idle_target_rpm - in->rpm;

    if (!in->running || in->rpm > c->idle_target_rpm + cfg->idle_band_rpm) {
        /* Well above idle, or not running. The loop has no business
         * here, and its integrator must not sit there accumulating a
         * demand it will dump the moment the driver lifts. */
        c->idle_i = 0.0f;
        c->idle_nm = 0.0f;
    } else {
        f32 i_next = c->idle_i + cfg->idle_ki * err * in->dt;
        /* Clamp the integrator itself, not just the output: an output
         * clamp with a free integrator is the classic windup, and here
         * it would show up as an idle that hangs after every stop. */
        i_next = tq_clampf(i_next, -cfg->idle_max_nm, cfg->idle_max_nm);
        c->idle_i = i_next;
        c->idle_nm = tq_clampf(cfg->idle_kp * err + c->idle_i,
                               0.0f, cfg->idle_max_nm);
    }

    /* ---- arbitration ------------------------------------------------ */
    /* The highest request wins, then limits cut it down. Idle and the
     * driver are both asking for the engine to make torque, so taking
     * the larger is right: the driver pressing the pedal at idle should
     * not have to overcome the idle controller, and lifting should not
     * drop below what idle needs to stay alight. */
    f32 target = (c->driver_nm > c->idle_nm) ? c->driver_nm : c->idle_nm;
    if (in->limit_nm >= 0.0f && target > in->limit_nm) {
        target = in->limit_nm;
    }
    c->target_nm = target;

    /* ---- inverse model: what air makes that torque ------------------ */
    c->air_target_g = tq_required_air(target, in->rpm, in->spark_deg,
                                      in->mbt_deg, in->lambda,
                                      in->map_kpa, e);
    if (c->air_target_g < 0.0f) {
        c->air_target_g = 0.0f;
    }

    /* ---- and what manifold pressure delivers that air --------------- */
    /* Inverting tq_air_mass: air = VE * (Vd/n) * MAP / (R*T), so
     * MAP = air * R * T / (VE * Vd_per_cyl). Asking the throttle for a
     * PRESSURE rather than an angle is what lets the same target serve a
     * naturally aspirated engine and a boosted one -- the wastegate is
     * just another way of reaching the same number. */
    f32 ve = (in->ve > 0.05f) ? in->ve : 0.05f;
    f32 vd = tq_vd_per_cyl_l(e);
    f32 t_charge = in->iat_k + 15.0f;
    if (vd > 1e-6f) {
        c->map_target_kpa = c->air_target_g * TQ_R_AIR * t_charge / (ve * vd);
    } else {
        c->map_target_kpa = in->map_kpa;
    }
    c->map_target_kpa = tq_clampf(c->map_target_kpa, 15.0f, 400.0f);
}
