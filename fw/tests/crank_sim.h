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
    f32 cam_at_deg;     /* cam edge fires once per cycle at this angle */
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
    s->cam_at_deg = 90.0f;
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

#endif /* CRANK_SIM_H */
