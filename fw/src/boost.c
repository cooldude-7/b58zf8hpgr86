#include "boost.h"

#include "hal.h"

boost_config_t boost_config_default(void)
{
    boost_config_t c;
    c.kp_map = 0.55f;
    c.ki_map = 1.1f;
    c.map_i_max = 70.0f;
    c.kp_pos = 0.030f;
    c.ki_pos = 0.10f;
    c.pos_i_max = 0.6f;
    c.open_pct = 100.0f;         /* no demand: gate open, no boost */
    c.overboost_kpa = 265.0f;
    c.lift_tps_pct = 4.0f;
    /* Default to holding the gate shut on a lift. It keeps the turbo
     * spinning, so the next application of throttle has boost waiting
     * rather than having to rebuild it -- and it is also what produces
     * the surge people fit blow-off valves to avoid. Calibratable
     * precisely because those two are the same physics wanted by
     * different people. */
    c.lift_hold_pct = 0.0f;
    c.lift_hold_s = 1.5f;
    return c;
}

void boost_init(boost_t *b, const boost_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*b); i++) {
        ((u8 *)b)[i] = 0;
    }
    b->cmd_pct = cfg->open_pct;
    b->actual_pct = cfg->open_pct;
}

void boost_update(boost_t *b, const boost_config_t *cfg, const boost_in_t *in)
{
    b->actual_pct = in->gate_pct;

    if (!in->running || !in->sensor_ok) {
        /* No engine, or no idea where the gate is. Open is the safe
         * default: an open wastegate cannot overboost, and a gate whose
         * position is unknown must not be driven toward closed. */
        b->enabled = false;
        b->duty = 0.0f;
        b->map_i = 0.0f;
        b->pos_i = 0.0f;
        b->cmd_pct = cfg->open_pct;
        hal_bridge_disable(HAL_BRIDGE_WASTEGATE);
        return;
    }
    b->enabled = true;

    /* ---- overboost overrides everything ----------------------------- */
    /* Ahead of the loop, not inside it: a PI controller winding its way
     * back from an overshoot is not a protection, it is a delay. */
    if (in->map_actual_kpa > cfg->overboost_kpa) {
        b->cmd_pct = 100.0f;
        b->map_i = 0.0f;
        b->lifting = false;
    } else {
        /* ---- lift-off ----------------------------------------------- */
        /* The hold has to be armed by the throttle being open, and
         * disarmed by taking it. Without that latch the expiry does
         * nothing: the timer runs out, the hold clears, and the next
         * call sees a closed throttle and starts the hold again -- so a
         * long overrun holds the gate shut forever, which is the one
         * thing lift_hold_s exists to stop. */
        bool lift_now = in->tps_pct < cfg->lift_tps_pct;
        if (!lift_now) {
            b->lifting = false;
            b->lift_armed = true;
        } else if (b->lift_armed) {
            b->lifting = true;
            b->lift_armed = false;
            b->lift_t = 0.0f;
        }
        if (b->lifting) {
            b->lift_t += in->dt;
            if (b->lift_t > cfg->lift_hold_s) {
                b->lifting = false;
            }
        }

        if (b->lifting) {
            /* Hold, and freeze the integrator. Letting it accumulate
             * against a pressure error nobody is trying to correct means
             * the gate slams the other way the moment the driver gets
             * back on it. */
            b->cmd_pct = cfg->lift_hold_pct;
        } else {
            /* ---- outer loop: pressure to gate position -------------- */
            /* Sign is inverted against the throttle: MORE pressure
             * wanted means LESS gate opening. */
            f32 err = in->map_target_kpa - in->map_actual_kpa;
            f32 i_next = b->map_i + cfg->ki_map * err * in->dt;
            i_next = tq_clampf(i_next, -cfg->map_i_max, cfg->map_i_max);

            f32 cmd = cfg->open_pct - (cfg->kp_map * err + i_next);
            f32 clamped = tq_clampf(cmd, 0.0f, 100.0f);
            bool pinned = (cmd > clamped && err < 0.0f)
                       || (cmd < clamped && err > 0.0f);
            if (!pinned) {
                b->map_i = i_next;
            }
            b->cmd_pct = clamped;
        }
    }

    /* ---- inner loop: position to duty ------------------------------- */
    f32 pos_err = b->cmd_pct - b->actual_pct;
    f32 pi_next = b->pos_i + cfg->ki_pos * pos_err * in->dt;
    pi_next = tq_clampf(pi_next, -cfg->pos_i_max, cfg->pos_i_max);
    f32 duty = cfg->kp_pos * pos_err + pi_next;
    f32 duty_c = tq_clampf(duty, -1.0f, 1.0f);
    bool duty_pinned = (duty > duty_c && pos_err > 0.0f)
                    || (duty < duty_c && pos_err < 0.0f);
    if (!duty_pinned) {
        b->pos_i = pi_next;
    }
    b->duty = duty_c;
    hal_bridge_pwm(HAL_BRIDGE_WASTEGATE, duty_c);
}
