#include "lambda.h"

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

lam_config_t lam_config_default(void)
{
    lam_config_t c;
    c.kp = 0.35f;
    c.ki = 0.55f;
    c.short_max = 0.25f;
    c.long_max = 0.20f;
    c.learn_tau_s = 20.0f;
    c.min_clt_k = 333.0f;         /* 60 C */
    c.settle_s = 0.35f;
    c.target_band = 0.04f;
    c.total_max = 0.30f;
    const f32 r[LAM_RPM_N] = { 1200.0f, 2500.0f, 4000.0f, 6000.0f };
    const f32 l[LAM_LOAD_N] = { 40.0f, 90.0f, 150.0f, 230.0f };
    for (u32 i = 0; i < LAM_RPM_N; i++) c.rpm_break[i] = r[i];
    for (u32 i = 0; i < LAM_LOAD_N; i++) c.load_break[i] = l[i];
    return c;
}

void lambda_init(lambda_t *l, const lam_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*l); i++) {
        ((u8 *)l)[i] = 0;
    }
    (void)cfg;
    l->short_trim = 1.0f;
    l->total = 1.0f;
    for (u32 a = 0; a < LAM_LOAD_N; a++) {
        for (u32 b = 0; b < LAM_RPM_N; b++) {
            l->long_trim[a][b] = 1.0f;
        }
    }
}

static u8 bucket(const f32 *breaks, u32 n, f32 v)
{
    for (u8 i = 0; i < (u8)n; i++) {
        if (v <= breaks[i]) return i;
    }
    return (u8)(n - 1u);
}

void lambda_update(lambda_t *l, const lam_config_t *cfg, const lam_in_t *in)
{
    u8 r = bucket(cfg->rpm_break, LAM_RPM_N, in->rpm);
    u8 ld = bucket(cfg->load_break, LAM_LOAD_N, in->load_kpa);
    if (r != l->cell_r || ld != l->cell_l) {
        /* A new operating region. The integrator holds the OLD cell's
         * accumulated correction, and carrying it across means the new
         * cell learns the old cell's error before it has measured
         * anything -- a lean region at idle teaches the same lean trim
         * to a perfectly healthy region at load. Continuity comes from
         * the new cell's own long term trim, which is what it is for. */
        l->cell_r = r;
        l->cell_l = ld;
        l->dwell_s = 0.0f;
        l->integ = 0.0f;
        l->short_trim = 1.0f;
    } else {
        l->dwell_s += in->dt;
    }

    /* ---- may the loop run at all? ----------------------------------- */
    bool rich_target = absf(in->lambda_target - 1.0f) > cfg->target_band;
    bool allow = in->sensor_ok
              && !in->inhibit
              && in->clt_k > cfg->min_clt_k
              && in->rpm > 400.0f
              && l->dwell_s > cfg->settle_s
              && !rich_target;
    /* A deliberately rich target at full load is not an error to correct
     * -- it is the calibration protecting the engine, and a feedback
     * loop chasing stoichiometric there would undo it. */

    l->closed = allow;
    if (!allow) {
        /* Hold the short term where it is rather than snapping to 1.0.
         * Snapping would put a fuelling step into the engine every time
         * the loop is gated, which is every gear change. */
        l->integ = tq_clampf(l->integ, -cfg->short_max, cfg->short_max);
    } else {
        /* Positive error means measured leaner than target, so add fuel. */
        f32 err = in->lambda_meas - in->lambda_target;
        f32 i_next = l->integ + cfg->ki * err * in->dt;
        i_next = tq_clampf(i_next, -cfg->short_max, cfg->short_max);
        l->integ = i_next;
        f32 corr = cfg->kp * err + l->integ;
        l->short_trim = 1.0f + tq_clampf(corr, -cfg->short_max, cfg->short_max);

        /* ---- learn ---------------------------------------------------- */
        /* The long term slowly absorbs whatever the short term keeps
         * having to do here, and the short term is measured RELATIVE to
         * it -- so once learned, the fast loop starts from zero error in
         * this region instead of rediscovering the same offset. */
        f32 *lt = &l->long_trim[ld][r];
        f32 k = in->dt / cfg->learn_tau_s;
        if (k > 1.0f) k = 1.0f;
        *lt += (l->short_trim - 1.0f) * (*lt) * k;
        *lt = tq_clampf(*lt, 1.0f - cfg->long_max, 1.0f + cfg->long_max);
        /* Hand the correction over: what long term took on, short term
         * gives back, so the two do not both chase the same error. */
        l->integ -= (l->short_trim - 1.0f) * k;
    }

    /* Clamp the PRODUCT, not only each factor. Two limits that are
     * individually reasonable multiply into one that is not: 20 % of
     * learning under 25 % of reaction is 50 % of fuel, which is a sensor
     * fault commanding a tune. */
    l->total = tq_clampf(l->long_trim[l->cell_l][l->cell_r] * l->short_trim,
                         1.0f - cfg->total_max, 1.0f + cfg->total_max);
}
