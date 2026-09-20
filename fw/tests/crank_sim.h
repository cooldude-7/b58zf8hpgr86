/* Synthetic crank and cam edges, so the decoder can be tested to
 * destruction without an engine. */
#ifndef CRANK_SIM_H
#define CRANK_SIM_H

#include "decoder.h"

typedef struct {
    f32 angle;          /* true crank angle, 0..720 */
    f32 rpm;
    tq_time_t t;        /* microseconds */
    u8 teeth_total;
    u8 teeth_missing;
    f32 gap_to_tdc;
    f32 last_angle;
} crank_sim_t;

static inline void crank_sim_init(crank_sim_t *s, const dec_config_t *cfg,
                                  f32 start_angle, f32 rpm)
{
    s->angle = start_angle;
    s->last_angle = start_angle;
    s->rpm = rpm;
    s->t = 1000000u;               /* start away from zero to catch wrap bugs */
    s->teeth_total = cfg->teeth_total;
    s->teeth_missing = cfg->teeth_missing;
    s->gap_to_tdc = cfg->gap_to_tdc_deg;
}

/* Is there a tooth at this crank angle? Teeth sit every 360/N degrees
 * measured from the first tooth after the gap; the last `missing` of each
 * revolution are ground off. */
static inline int crank_sim_tooth_index(const crank_sim_t *s, f32 angle_360)
{
    f32 deg_per = 360.0f / (f32)s->teeth_total;
    f32 rel = angle_360 - s->gap_to_tdc;
    while (rel < 0.0f) rel += 360.0f;
    while (rel >= 360.0f) rel -= 360.0f;
    f32 fidx = rel / deg_per;
    int idx = (int)(fidx + 0.5f);
    if (fabsf(fidx - (f32)idx) > 0.01f) return -1;
    if (idx >= s->teeth_total - s->teeth_missing) return -1;  /* in the gap */
    return idx % s->teeth_total;
}

/* ---- cam pattern generation ----------------------------------------- */
/* Does angle `a` fall in the crank window (before, after], allowing for
 * the window wrapping through 720 back to 0? */
static inline bool cam_sim_in_window(f32 a, f32 before, f32 after)
{
    if (after >= before) return (a > before && a <= after);
    return (a > before || a <= after);
}

typedef struct {
    u8 idx;       /* which pattern edge */
    f32 frac;     /* where in the step it fell, 0..1, for the timestamp */
} cam_sim_hit_t;

/* Which edges of `p` are crossed by moving the crank from `before` to
 * `after`, with the whole pattern displaced by `advance` CRANK degrees
 * (positive = advanced, so edges arrive earlier).
 *
 * Displacing the pattern rigidly is the point: a real phaser moves every
 * lobe by the same amount, which is exactly why the spacings between them
 * survive and can be used to identify position.
 *
 * `frac` matters more than it looks. Real hardware latches the cam edge
 * timestamp in a capture register, so it is exact. A simulator that
 * instead reports the edge at the end of the tooth it fell inside makes
 * every edge late by up to a whole tooth, which shows up as a standing
 * bias in measured cam advance -- and then the test is measuring the
 * simulator rather than the decoder. */
static inline u8 cam_sim_crossed(const dec_cam_pattern_t *p, f32 before,
                                 f32 after, f32 advance,
                                 cam_sim_hit_t *out, u8 cap)
{
    f32 span = after - before;
    if (span <= 0.0f) span += TQ_CYCLE_DEG;
    u8 n = 0;
    for (u8 i = 0; i < p->n_edges && n < cap; i++) {
        f32 at = tq_wrap_deg(p->e[i].angle_deg - advance);
        if (!cam_sim_in_window(at, before, after)) continue;
        f32 into = at - before;
        if (into < 0.0f) into += TQ_CYCLE_DEG;
        out[n].idx = i;
        out[n].frac = (span > 0.0f) ? (into / span) : 0.0f;
        n++;
    }
    return n;
}

#endif /* CRANK_SIM_H */
