#include "enrich.h"

enr_config_t enr_config_default(void)
{
    /* PROVISIONAL. Every number here is a starting point that gets
     * argued with by a real engine on a real cold morning -- these are
     * the corrections that no amount of bench work calibrates, because
     * what they compensate for is fuel condensing on metal. */
    enr_config_t c;
    const f32 k[ENR_CLT_N]     = { 233.0f, 253.0f, 273.0f, 293.0f,
                                   333.0f, 363.0f };
    /* -40 C  -20 C    0 C   20 C   60 C   90 C */
    const f32 crank[ENR_CLT_N] = {  6.0f,  4.2f,  2.9f,  2.1f,  1.4f, 1.15f };
    const f32 warm[ENR_CLT_N]  = {  1.7f,  1.5f,  1.32f, 1.20f, 1.06f, 1.0f };
    for (u32 i = 0; i < ENR_CLT_N; i++) {
        c.clt_k[i] = k[i];
        c.crank_mult[i] = crank[i];
        c.warm_mult[i] = warm[i];
    }
    c.astart_extra = 0.45f;
    c.astart_tau_s = 3.0f;

    /* Fraction of extra fuel per kPa/s of manifold rise. A brisk tip-in
     * is several hundred kPa/s, so this number is small by construction
     * -- 0.010 would ask for six times the fuel on a normal throttle
     * movement, which pins the correction against its own ceiling and
     * makes the whole thing a constant. */
    c.accel_gain = 3.0e-4f;
    c.accel_tau_s = 0.25f;
    c.accel_max = 1.5f;
    c.accel_cold_scale = 2.5f;    /* at the coldest point on the axis */

    c.dfco_rpm = 1400.0f;
    c.dfco_tps_pct = 3.0f;
    c.dfco_resume_rpm = 1100.0f;
    c.dfco_clt_min_k = 333.0f;    /* 60 C */
    return c;
}

void enrich_init(enrich_t *e)
{
    for (u32 i = 0; i < sizeof(*e); i++) {
        ((u8 *)e)[i] = 0;
    }
    e->crank = e->astart = e->warm = e->accel = 1.0f;
    e->total = 1.0f;
}

void enrich_update(enrich_t *e, const enr_config_t *cfg, const enr_in_t *in)
{
    /* ---- cranking --------------------------------------------------- */
    if (in->cranking) {
        e->crank = tq_interp(cfg->clt_k, cfg->crank_mult, ENR_CLT_N, in->clt_k);
        /* Hold the after-start timer at zero while it is still turning
         * over, so the decay starts when the engine CATCHES rather than
         * when the key was turned. A long crank would otherwise use up
         * the whole after-start period before the first firing. */
        e->astart_t = 0.0f;
        e->was_cranking = true;
    } else {
        e->crank = 1.0f;
        if (in->running) {
            e->astart_t += in->dt;
        } else {
            /* Not cranking and not running: stopped. Re-arm. */
            e->astart_t = 0.0f;
            e->was_cranking = false;
        }
    }

    /* ---- after-start ------------------------------------------------ */
    if (in->running && e->was_cranking && cfg->astart_tau_s > 1e-3f) {
        /* Exponential decay, evaluated from elapsed time rather than
         * accumulated per tick, so a missed task does not change the
         * total amount of fuel the correction delivers. */
        f32 n = e->astart_t / cfg->astart_tau_s;
        f32 decay = 1.0f;
        /* exp(-n) without libm: successive halving is plenty here and
         * costs nothing in an ISR-adjacent path. */
        for (f32 r = n; r > 0.0f; r -= 1.0f) {
            decay *= (r >= 1.0f) ? 0.3679f : (1.0f - 0.6321f * r);
        }
        e->astart = 1.0f + cfg->astart_extra * decay;
        if (decay < 0.01f) {
            e->was_cranking = false;   /* done; stop recomputing it */
            e->astart = 1.0f;
        }
    } else {
        e->astart = 1.0f;
    }

    /* ---- warmup ----------------------------------------------------- */
    e->warm = tq_interp(cfg->clt_k, cfg->warm_mult, ENR_CLT_N, in->clt_k);

    /* ---- acceleration ----------------------------------------------- */
    /* Rate of change of manifold pressure. A fast opening fills the
     * manifold before the fuel film on the port walls re-establishes, so
     * the cylinder goes momentarily lean and the engine stumbles. */
    f32 rate = 0.0f;
    if (e->have_prev && in->dt > 1e-6f) {
        rate = (in->map_kpa - e->map_prev) / in->dt;
    }
    e->map_prev = in->map_kpa;
    e->have_prev = true;

    if (rate > 0.0f) {
        /* Cold multiplies it, because wall wetting is far worse on cold
         * metal -- this is why a cold engine stumbles on a tip-in that
         * a warm one takes cleanly. */
        f32 cold_f = tq_interp(cfg->clt_k, cfg->warm_mult, ENR_CLT_N, in->clt_k);
        f32 scale = 1.0f + (cold_f - 1.0f) * cfg->accel_cold_scale;
        f32 kick = rate * cfg->accel_gain * scale;
        if (kick > e->accel_state) {
            e->accel_state = kick;     /* rises at once */
        }
    }
    if (cfg->accel_tau_s > 1e-3f) {
        f32 k = in->dt / cfg->accel_tau_s;
        if (k > 1.0f) k = 1.0f;
        e->accel_state -= e->accel_state * k;   /* and decays away */
    }
    e->accel = 1.0f + e->accel_state;
    if (e->accel > cfg->accel_max) {
        e->accel = cfg->accel_max;
    }

    /* ---- deceleration fuel cut -------------------------------------- */
    /* Hysteresis on rpm, so fuel comes back well before the engine drops
     * to idle rather than at the moment it arrives there. Never while
     * cold, because a cold engine that is cut may not relight. */
    bool closed = in->tps_pct < cfg->dfco_tps_pct;
    bool warm_enough = in->clt_k > cfg->dfco_clt_min_k;
    if (!in->running || !closed || !warm_enough) {
        e->fuel_cut = false;
    } else if (e->fuel_cut) {
        e->fuel_cut = (in->rpm > cfg->dfco_resume_rpm);
    } else {
        e->fuel_cut = (in->rpm > cfg->dfco_rpm);
    }

    e->total = e->crank * e->astart * e->warm * e->accel;
}
