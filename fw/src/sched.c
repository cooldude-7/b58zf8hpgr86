#include "sched.h"

void sched_init(sched_t *s, u8 n_cyl)
{
    for (u32 i = 0; i < sizeof(*s); i++) {
        ((u8 *)s)[i] = 0;
    }
    s->n_cyl = n_cyl > TQ_MAX_CYL ? TQ_MAX_CYL : n_cyl;
    s->min_dwell_us = 1200;
    s->max_dwell_us = 6000;
    s->lookahead_deg = 90.0f;
    for (u8 c = 0; c < s->n_cyl; c++) {
        s->cyl[c].tdc_deg = (TQ_CYCLE_DEG / (f32)s->n_cyl) * (f32)c;
        s->cyl[c].spark_enabled = true;
        s->cyl[c].fuel_enabled = true;
        s->cyl[c].dwell_us = 2500;
        s->cyl[c].soi_deg = 300.0f;
    }
}

void sched_set_tdc(sched_t *s, u8 cyl, f32 tdc_deg)
{
    if (cyl < s->n_cyl) {
        s->cyl[cyl].tdc_deg = tq_wrap_deg(tdc_deg);
    }
}

void sched_set_spark(sched_t *s, u8 cyl, f32 advance_deg, u32 dwell_us)
{
    if (cyl >= s->n_cyl) {
        return;
    }
    if (dwell_us < s->min_dwell_us) dwell_us = s->min_dwell_us;
    if (dwell_us > s->max_dwell_us) dwell_us = s->max_dwell_us;
    s->cyl[cyl].spark_advance = advance_deg;
    s->cyl[cyl].dwell_us = dwell_us;
}

void sched_set_injection(sched_t *s, u8 cyl, f32 soi_deg, u32 pw_us)
{
    if (cyl >= s->n_cyl) {
        return;
    }
    s->cyl[cyl].soi_deg = soi_deg;
    s->cyl[cyl].pw_us = pw_us;
}

void sched_enable_spark(sched_t *s, bool on)
{
    for (u8 c = 0; c < s->n_cyl; c++) {
        s->cyl[c].spark_enabled = on;
    }
}

void sched_enable_fuel(sched_t *s, bool on)
{
    for (u8 c = 0; c < s->n_cyl; c++) {
        s->cyl[c].fuel_enabled = on;
    }
}

void sched_cut_cylinder(sched_t *s, u8 cyl, bool spark_on, bool fuel_on)
{
    if (cyl < s->n_cyl) {
        s->cyl[cyl].spark_enabled = spark_on;
        s->cyl[cyl].fuel_enabled = fuel_on;
    }
}

void sched_all_off(sched_t *s)
{
    for (u8 c = 0; c < s->n_cyl; c++) {
        s->cyl[c].spark_armed = false;
        s->cyl[c].fuel_armed = false;
        hal_out_cancel((hal_out_t)(HAL_OUT_COIL_1 + c));
        hal_out_cancel((hal_out_t)(HAL_OUT_INJ_1 + c));
    }
}

void sched_update(sched_t *s, const decoder_t *d, tq_time_t now_us)
{
    /* Sequential operation needs to know which stroke we are on. Without
     * that the engine must not be fired at all: half the sparks would
     * land on an open intake valve. */
    if (!decoder_has_phase(d)) {
        sched_all_off(s);
        return;
    }

    f32 now_angle = decoder_angle_at(d, now_us);

    for (u8 c = 0; c < s->n_cyl; c++) {
        sched_cyl_t *cy = &s->cyl[c];

        /* ---- spark ---------------------------------------------------- */
        f32 fire_at = tq_wrap_deg(cy->tdc_deg - cy->spark_advance);
        f32 to_fire = tq_wrap_deg(fire_at - now_angle);

        if (!cy->spark_armed && cy->spark_enabled
            && to_fire <= s->lookahead_deg) {
            tq_time_t spark_us;
            if (decoder_time_for_angle(d, now_us, fire_at, &spark_us)) {
                tq_time_t dwell_us = spark_us - cy->dwell_us;
                /* If the charge should already have begun, start it now
                 * and accept a short dwell rather than skipping the
                 * cylinder: a weak spark beats no spark. */
                if (!tq_after(dwell_us, now_us)) {
                    dwell_us = now_us + 1u;
                    if (!tq_after(spark_us, dwell_us + s->min_dwell_us)) {
                        spark_us = dwell_us + s->min_dwell_us;
                        s->missed_events++;
                    }
                }
                if (hal_out_schedule((hal_out_t)(HAL_OUT_COIL_1 + c),
                                     dwell_us, spark_us)) {
                    cy->spark_armed = true;
                    cy->spark_at = spark_us;
                    cy->dwell_at = dwell_us;
                    s->spark_events++;
                }
            }
        } else if (cy->spark_armed && !cy->spark_enabled) {
            /* A cut arrived after arming. Dropping a charging coil is a
             * misfire, so the charge is allowed to finish and the coil is
             * fired; the cut takes effect on the next cycle. Fuel is the
             * fast way to cut torque, and it has already been stopped. */
            if (!hal_out_is_active((hal_out_t)(HAL_OUT_COIL_1 + c))) {
                hal_out_cancel((hal_out_t)(HAL_OUT_COIL_1 + c));
                cy->spark_armed = false;
            }
        }

        if (cy->spark_armed && tq_after(now_us, cy->spark_at)) {
            cy->spark_armed = false;        /* it has fired; re-arm next cycle */
        }

        /* ---- injection ------------------------------------------------ */
        f32 open_at = tq_wrap_deg(cy->tdc_deg - cy->soi_deg);
        f32 to_open = tq_wrap_deg(open_at - now_angle);

        if (!cy->fuel_armed && cy->fuel_enabled && cy->pw_us > 0
            && to_open <= s->lookahead_deg) {
            tq_time_t open_us;
            if (decoder_time_for_angle(d, now_us, open_at, &open_us)) {
                if (hal_out_schedule((hal_out_t)(HAL_OUT_INJ_1 + c),
                                     open_us, open_us + cy->pw_us)) {
                    cy->fuel_armed = true;
                    s->fuel_events++;
                }
            }
        } else if (cy->fuel_armed && !cy->fuel_enabled) {
            /* Fuel CAN be retracted mid-pulse: shutting the injector
             * early only means less fuel, never an unburnt charge. */
            hal_out_cancel((hal_out_t)(HAL_OUT_INJ_1 + c));
            cy->fuel_armed = false;
        }

        if (cy->fuel_armed
            && !hal_out_is_active((hal_out_t)(HAL_OUT_INJ_1 + c))
            && to_open > s->lookahead_deg) {
            cy->fuel_armed = false;
        }
    }
}
