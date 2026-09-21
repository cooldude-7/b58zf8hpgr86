#include "aux.h"

#include "hal.h"

aux_config_t aux_config_default(void)
{
    aux_config_t c;
    c.prime_s = 2.0f;
    /* Short, but not zero. A momentary decoder dropout at speed should
     * not stop the pump -- that would stall an engine that was about to
     * recover on the next tooth. Long enough to ride out a glitch, short
     * enough to matter after an impact. */
    c.pump_sync_grace_s = 1.0f;
    c.fan_on_k = 369.0f;         /* 96 C */
    c.fan_off_k = 363.0f;        /* 90 C */
    c.fan_runon_s = 120.0f;
    c.tacho_pulses_per_rev = 2.0f;   /* a four-cylinder's two sparks */
    return c;
}

void aux_init(aux_t *a)
{
    for (u32 i = 0; i < sizeof(*a); i++) {
        ((u8 *)a)[i] = 0;
    }
}

void aux_update(aux_t *a, const aux_config_t *cfg, const aux_in_t *in)
{
    /* ---- fuel pump --------------------------------------------------- */
    if (!a->primed) {
        a->prime_t += in->dt;
        a->pump = true;                       /* prime: fill the rail */
        if (a->prime_t >= cfg->prime_s) {
            a->primed = true;
        }
    }
    if (a->primed) {
        a->nosync_t = in->has_sync ? 0.0f : a->nosync_t + in->dt;
        a->pump = in->has_sync || (a->nosync_t < cfg->pump_sync_grace_s);
    }

    /* ---- cooling fan ------------------------------------------------- */
    /* Hysteresis rather than a threshold, because a fan that switches on
     * and off at the same temperature does so several times a minute. */
    if (in->clt_k > cfg->fan_on_k) {
        a->fan = true;
    } else if (in->clt_k < cfg->fan_off_k) {
        a->fan = in->running ? false : a->fan;
    }
    if (!in->running) {
        /* Run-on: a turbocharged engine keeps making heat after it stops
         * because there is no coolant flow and a hot turbine soaking it
         * back into the head. */
        if (a->fan) {
            a->runon_t += in->dt;
            if (a->runon_t > cfg->fan_runon_s || in->clt_k < cfg->fan_off_k) {
                a->fan = false;
            }
        }
    } else {
        a->runon_t = 0.0f;
    }

    /* ---- tacho ------------------------------------------------------- */
    a->tacho_hz = (in->rpm > 0.0f)
                ? in->rpm / 60.0f * cfg->tacho_pulses_per_rev : 0.0f;

    /* ---- lamp -------------------------------------------------------- */
    a->mil = in->faulted;

    hal_sw_set(HAL_SW_FUEL_PUMP, a->pump);
    hal_sw_set(HAL_SW_FAN, a->fan);
    hal_sw_set(HAL_SW_MIL, a->mil);
    hal_sw_frequency(HAL_SW_TACHO, a->tacho_hz);
}
