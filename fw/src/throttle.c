#include "throttle.h"

#include "hal.h"

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

thr_config_t thr_config_default(void)
{
    /* PROVISIONAL. The inner loop's gains belong to a specific throttle
     * body and want a bench sweep; these are sized to be sluggish rather
     * than lively, because a throttle that oscillates is a throttle that
     * destroys its own gearbox. */
    thr_config_t c;
    c.kp_map = 0.45f;
    c.ki_map = 0.9f;
    c.map_i_max = 60.0f;
    c.kp_pos = 0.035f;
    c.ki_pos = 0.12f;
    c.pos_i_max = 0.6f;
    c.limp_pos_pct = 7.0f;
    c.min_pos_pct = 0.0f;
    c.max_pos_pct = 100.0f;
    c.disagree_pct = 8.0f;
    return c;
}

void throttle_init(throttle_t *t, const thr_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*t); i++) {
        ((u8 *)t)[i] = 0;
    }
    t->cmd_pct = cfg->limp_pos_pct;
    t->actual_pct = cfg->limp_pos_pct;
    t->plausible = true;
}

void throttle_update(throttle_t *t, const thr_config_t *cfg,
                     const thr_in_t *in)
{
    /* ---- do the two sensors agree? ---------------------------------- */
    /* If they do not, we do not know where the plate is, and a position
     * loop run on a number that might be wrong will drive the plate to
     * a place nobody asked for. Give up and let the spring decide. */
    t->plausible = absf(in->tps_a_pct - in->tps_b_pct) <= cfg->disagree_pct;
    t->actual_pct = 0.5f * (in->tps_a_pct + in->tps_b_pct);

    if (!in->allow || !t->plausible) {
        t->enabled = false;
        t->duty = 0.0f;
        t->map_i = 0.0f;
        t->pos_i = 0.0f;
        /* Report the limp position as the command, so the Level 2
         * monitor's tracking check compares like with like instead of
         * seeing a command it was never going to follow. */
        t->cmd_pct = cfg->limp_pos_pct;
        hal_bridge_disable(HAL_BRIDGE_THROTTLE);
        return;
    }
    t->enabled = true;

    /* ---- outer loop: pressure to position --------------------------- */
    f32 map_err = in->map_target_kpa - in->map_actual_kpa;
    f32 i_next = t->map_i + cfg->ki_map * map_err * in->dt;
    i_next = tq_clampf(i_next, -cfg->map_i_max, cfg->map_i_max);

    f32 cmd = cfg->kp_map * map_err + i_next;
    f32 clamped = tq_clampf(cmd, cfg->min_pos_pct, cfg->max_pos_pct);
    /* Only integrate when the command is not already pinned against a
     * stop in the direction the error is pushing. A wide-open throttle
     * that keeps integrating takes just as long to come back. */
    bool pinned = (cmd > clamped && map_err > 0.0f)
               || (cmd < clamped && map_err < 0.0f);
    if (!pinned) {
        t->map_i = i_next;
    }
    t->cmd_pct = clamped;

    /* ---- inner loop: position to duty ------------------------------- */
    f32 pos_err = t->cmd_pct - t->actual_pct;
    f32 pi_next = t->pos_i + cfg->ki_pos * pos_err * in->dt;
    pi_next = tq_clampf(pi_next, -cfg->pos_i_max, cfg->pos_i_max);

    f32 duty = cfg->kp_pos * pos_err + pi_next;
    f32 duty_c = tq_clampf(duty, -1.0f, 1.0f);
    bool duty_pinned = (duty > duty_c && pos_err > 0.0f)
                    || (duty < duty_c && pos_err < 0.0f);
    if (!duty_pinned) {
        t->pos_i = pi_next;
    }
    t->duty = duty_c;
    hal_bridge_pwm(HAL_BRIDGE_THROTTLE, duty_c);
}
