#include "vanos.h"

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

van_config_t vanos_config_default(void)
{
    /* PROVISIONAL. kv_deg_s is a plant gain and belongs on a bench with a
     * scope, not in a header. It is sized here so the loop is sluggish
     * rather than lively, because an over-eager phaser loop hunts and a
     * hunting cam is a rough idle. */
    van_config_t c;
    c.kv_deg_s = 300.0f;       /* crank deg/s at full duty away from null */
    /* Sized together, not independently. The closed loop is
     *   lambda^2 + kv*kp*lambda + kv*ki
     * so kp sets the damping and ki the speed. These give roots at about
     * -1.2 and -3.3, i.e. a slow mode near 0.8 s -- deliberately short of
     * critical, because the cam measurement is averaged over a whole cam
     * pattern and therefore lags by one engine cycle (~150 ms at idle).
     * Lag plus a tight loop hunts, and a hunting cam is a rough idle. */
    c.kp = 0.015f;
    c.ki = 0.015f;
    c.kd = 0.0f;               /* see the header: zero unless lag bites */
    c.null_seed = 0.50f;
    c.stationary_dps = 6.0f;
    c.min_oil_kpa = 150.0f;
    c.min_oil_k = 273.0f + 20.0f;
    c.min_rpm = 500.0f;
    c.stale_limit_us = 250000u;      /* a cycle at idle is ~150 ms */
    c.fault_err_deg = 12.0f;
    c.fault_time_s = 2.0f;
    return c;
}

void vanos_init(vanos_t *v, const van_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*v); i++) {
        ((u8 *)v)[i] = 0;
    }
    v->cfg = *cfg;
    for (u8 i = 0; i < VAN_N_CAM; i++) {
        v->cam[i].null_duty = cfg->null_seed;
        v->cam[i].state = VAN_OFF;
    }
}

bool vanos_position_known(const vanos_t *v, u8 cam)
{
    return cam < VAN_N_CAM && v->cam[cam].have_meas;
}

/* De-energize. BMW's central valve locks the unit with a pin when the
 * actuator is de-energized, so this is a park, not a drift. It is why
 * shutdown needs no manoeuvre and no timeout, and therefore raises no
 * spurious fault every time the engine is switched off. */
static void park(vanos_t *v, u8 i)
{
    v->cam[i].duty = 0.0f;
    v->cam[i].t_err = 0.0f;
    hal_ocv_pwm((hal_ocv_t)(HAL_OCV_CAM_1 + i), 0.0f);
}

static void cam_update(vanos_t *v, u8 i, const van_inputs_t *in)
{
    van_cam_t *c = &v->cam[i];
    const van_config_t *cfg = &v->cfg;

    if (c->state == VAN_FAULT) {
        park(v, i);
        return;
    }

    /* ---- is there a measurement worth acting on? -------------------- */
    bool fresh = in->meas_valid[i] && in->meas_age_us[i] <= cfg->stale_limit_us;
    if (fresh) {
        /* Rate, from consecutive DISTINCT measurements. Dividing by dt of
         * the task rather than by the time between samples would report a
         * rate of zero on every tick that brought nothing new, and the
         * learner keys off "is it moving". */
        if (c->have_meas && in->now_us != c->last_stamp) {
            f32 span = (f32)(i32)(in->now_us - c->last_stamp) * 1.0e-6f;
            if (span > 1.0e-4f) {
                c->rate_deg_s = (in->meas_deg[i] - c->meas_deg) / span;
            }
        }
        c->meas_deg = in->meas_deg[i];
        c->last_stamp = in->now_us;
        c->have_meas = true;
    }

    /* ---- gates ------------------------------------------------------ */
    bool has_authority = in->running
                      && in->rpm >= cfg->min_rpm
                      && in->oil_kpa >= cfg->min_oil_kpa
                      && in->oil_k >= cfg->min_oil_k;
    if (!has_authority || !fresh) {
        /* No oil, no engine, or no idea where the cam is. Park it and
         * hold the learned duty -- do not decay it, it is still the best
         * estimate we have for the next time there IS authority. There is
         * no integrator to wind up because there is no integrator. */
        c->state = VAN_OFF;
        c->rate_deg_s = 0.0f;
        park(v, i);
        return;
    }

    c->state = VAN_CLOSED_LOOP;
    c->target_deg = tq_clampf(in->target_deg[i], in->adv_min[i], in->adv_max[i]);

    /* Work in "travel away from park", so one control law serves a cam
     * that advances and one that retards. dir folds the hardware's
     * direction into the error instead of into the gains. */
    f32 dir = (in->travel_dir[i] < 0.0f) ? -1.0f : 1.0f;
    f32 err = (c->target_deg - c->meas_deg) * dir;
    f32 raw = c->null_duty + cfg->kp * err - cfg->kd * (c->rate_deg_s * dir);
    f32 duty = tq_clampf(raw, 0.0f, 1.0f);
    c->duty = duty;
    hal_ocv_pwm((hal_ocv_t)(HAL_OCV_CAM_1 + i), duty);

    /* ---- find the holding duty -------------------------------------- */
    /* null_duty is an integrator on the position error, and it is the
     * whole reason this loop works. A proportional term alone has zero
     * steady-state error on an integrating plant ONLY if the holding duty
     * is exactly right; it never is, so P alone parks the cam at an
     * offset of (null_true - null_duty)/kp and sits there.
     *
     * It integrates unconditionally rather than only while the cam is
     * standing still. Gating it on the cam being stationary sounds
     * appealing -- a stationary cam is by definition being held by the
     * applied duty -- but it deadlocks: a badly wrong holding duty drives
     * the cam to a rail, the pin locks it, and the gate then refuses to
     * learn precisely when the estimate is worst.
     *
     * Anti-windup: stop integrating in whichever direction is already
     * pinned against the clamp. Without this a cam parked on its
     * mechanical stop winds the integrator to the end of its range and
     * then takes just as long to unwind on the way back. */
    bool on_stop = (c->meas_deg <= in->adv_min[i] + 1.0f)
                || (c->meas_deg >= in->adv_max[i] - 1.0f);
    bool pinned_hi = (raw > duty) && (err > 0.0f);
    bool pinned_lo = (raw < duty) && (err < 0.0f);
    if (!on_stop && !pinned_hi && !pinned_lo) {
        c->null_duty += cfg->ki * err * in->dt;
        c->null_duty = tq_clampf(c->null_duty, 0.02f, 0.98f);
    }

    /* ---- faults ----------------------------------------------------- */
    /* Commanded, with oil, and it did not arrive. Note what is NOT a
     * fault: a cam that has not moved because the loop was gated out, or
     * because it is pinned against its own mechanical stop by a target
     * the calibration clamped there. */
    if (absf(err) > cfg->fault_err_deg && !on_stop) {
        c->t_err += in->dt;
        if (c->t_err > cfg->fault_time_s) {
            c->fault = VAN_F_NOT_REACHED;
            c->state = VAN_FAULT;
            park(v, i);
            return;
        }
    } else {
        c->t_err = 0.0f;
    }

    /* A cam that moves while the valve is de-energized. There is no
     * ambiguity in this one: zero duty means the locking pin is holding
     * the unit, so motion here is mechanical, not a control transient.
     *
     * The tempting broader rule -- "moving away from the command" -- is
     * wrong, and dangerously so. It is exactly what a healthy cam does
     * while the holding duty is still being learned, so it fires on a
     * normal cold start and latches a fault on a working phaser. */
    if (duty <= 0.01f && absf(c->rate_deg_s) > cfg->stationary_dps) {
        c->fault = VAN_F_RUNAWAY;
        c->state = VAN_FAULT;
        park(v, i);
    }
}

void vanos_update(vanos_t *v, const van_inputs_t *in)
{
    for (u8 i = 0; i < VAN_N_CAM; i++) {
        cam_update(v, i, in);
    }
}
