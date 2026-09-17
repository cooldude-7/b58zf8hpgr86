#include "fuel.h"

#include <math.h>

tq_injector_t tq_injector_default(void)
{
    tq_injector_t i;
    i.flow_cc_min = 1050.0f;
    i.rated_dp_kpa = 350.0f;
    i.deadtime_ms = 0.90f;
    i.deadtime_slope_ms_v = -0.09f;   /* dead time grows as voltage falls */
    i.min_pulse_ms = 0.35f;
    return i;
}

f32 tq_fuel_mass(f32 air_g, f32 lambda_target, const tq_engine_t *e)
{
    f32 lam = lambda_target < 0.3f ? 0.3f : lambda_target;
    return air_g / (e->afr_stoich * lam);
}

u32 tq_pulse_width_us(f32 fuel_g, f32 rail_kpa, f32 cylinder_kpa,
                      f32 battery_v, const tq_injector_t *inj)
{
    if (fuel_g <= 0.0f) {
        return 0;
    }
    /* What the injector works against is the difference between rail and
     * cylinder pressure, not the rail pressure alone. On a direct
     * injection engine at high load that difference is meaningfully
     * smaller than the rail reading. */
    f32 dp = rail_kpa - cylinder_kpa;
    if (dp < 50.0f) {
        dp = 50.0f;                   /* refuse to divide by a stalled rail */
    }
    f32 flow_g_s = inj->flow_cc_min / 60.0f * TQ_FUEL_DENSITY_G_CC
                   * sqrtf(dp / inj->rated_dp_kpa);
    f32 open_ms = fuel_g / flow_g_s * 1000.0f;

    f32 dead = inj->deadtime_ms + inj->deadtime_slope_ms_v * (battery_v - 13.8f);
    if (dead < 0.0f) {
        dead = 0.0f;
    }
    /* Below the linear region the injector delivers an unpredictable
     * amount, so ask for nothing rather than something unknown. */
    if (open_ms < inj->min_pulse_ms) {
        return 0;
    }
    return (u32)((open_ms + dead) * 1000.0f);
}

f32 tq_injector_duty(u32 pw_us, f32 rpm)
{
    if (rpm < 100.0f) {
        return 0.0f;
    }
    f32 period_us = 120.0e6f / rpm;   /* one injection per two revolutions */
    f32 duty = (f32)pw_us / period_us * 100.0f;
    return duty > 100.0f ? 100.0f : duty;
}

void tq_hpfp_init(tq_hpfp_t *h, f32 lobes_per_cycle)
{
    h->target_kpa = 5000.0f;
    h->kp = 2.0e-4f;
    h->ki = 6.0e-4f;
    h->integral = 0.0f;
    h->duty = 0.0f;
    h->lobes_per_cycle = lobes_per_cycle;
    h->enabled = false;
}

f32 tq_hpfp_update(tq_hpfp_t *h, f32 dt_s, f32 measured_kpa,
                   f32 demand_g_per_cycle)
{
    if (!h->enabled) {
        h->integral = 0.0f;
        h->duty = 0.0f;
        return 0.0f;
    }
    f32 err = h->target_kpa - measured_kpa;

    /* Feed forward what the injectors are about to take. Without this the
     * loop only reacts after the rail has already dropped, which on a
     * tip-in is exactly when the fuelling error matters most. */
    f32 ff = demand_g_per_cycle * 0.25f;

    h->integral += err * h->ki * dt_s;
    h->integral = tq_clampf(h->integral, -1.0f, 1.0f);

    f32 duty = ff + err * h->kp + h->integral;
    duty = tq_clampf(duty, 0.0f, 1.0f);

    /* Anti-windup: if the output is saturated the integral must not keep
     * growing, or the rail overshoots badly when demand falls. */
    if ((duty >= 1.0f && err > 0.0f) || (duty <= 0.0f && err < 0.0f)) {
        h->integral -= err * h->ki * dt_s;
    }
    h->duty = duty;
    return duty;
}
