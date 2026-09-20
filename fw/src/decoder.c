#include "decoder.h"

#include <math.h>

dec_config_t decoder_config_b48(void)
{
    /* PROVISIONAL. Every number here must be replaced with a scope
     * measurement before this runs an engine -- see fw/README.md and
     * docs/ultracode-plan.md. tools/trigger turns a capture into this.
     *
     * 60-2 is confirmed for the BMW DME family of this era (BMW ST055
     * states the DME "increments the crankshaft position by 6 degrees"
     * per tooth, and 360/6 = 60) but is NOT published for the B48
     * specifically. The sensor is Hall, not VR. */
    dec_config_t c;
    for (u32 i = 0; i < sizeof(c); i++) {
        ((u8 *)&c)[i] = 0;
    }
    c.teeth_total = 60;
    c.teeth_missing = 2;
    c.gap_ratio = 1.6f;
    c.noise_ratio = 0.45f;
    c.gap_to_tdc_deg = 114.0f;

    /* Cam patterns. These crank angles are the rusEFI project's rising
     * edges measured from a real BMW N52 capture, doubled from cam into
     * crank degrees. An N52 is not a B48, so treat the SHAPE as right --
     * three lobes, deliberately unequal, uniquely identifiable from two
     * consecutive spacings -- and the NUMBERS as a placeholder.
     *
     * Spacings are 180 / 220 / 320 crank degrees. All different, which is
     * what lets two intervals name the position outright. */
    c.cam[0].n_edges = 3;                  /* intake */
    c.cam[0].e[0].angle_deg = 181.0f; c.cam[0].e[0].rising = true;
    c.cam[0].e[1].angle_deg = 361.0f; c.cam[0].e[1].rising = true;
    c.cam[0].e[2].angle_deg = 581.0f; c.cam[0].e[2].rising = true;
    /* Intake parks fully retarded and advances from there. ~35 cam
     * degrees of authority is ~70 crank degrees. */
    c.cam[0].adv_min_deg = -8.0f;          /* a little slack below park */
    c.cam[0].adv_max_deg = 70.0f;
    c.cam[0].match_tol_deg = 8.0f;
    c.cam[0].slew_max_dps = 400.0f;

    /* Exhaust parks fully ADVANCED and retards from there, so its range
     * is negative. A single unsigned authority cannot express this. */
    c.cam[1].n_edges = 3;
    c.cam[1].e[0].angle_deg = 181.0f; c.cam[1].e[0].rising = true;
    c.cam[1].e[1].angle_deg = 361.0f; c.cam[1].e[1].rising = true;
    c.cam[1].e[2].angle_deg = 581.0f; c.cam[1].e[2].rising = true;
    c.cam[1].adv_min_deg = -60.0f;
    c.cam[1].adv_max_deg = 8.0f;
    c.cam[1].match_tol_deg = 8.0f;
    c.cam[1].slew_max_dps = 400.0f;
    return c;
}

static void lose_sync(decoder_t *d, dec_loss_t why)
{
    if (d->state != DEC_SEEKING) {
        d->loss_count++;
    }
    d->state = DEC_SEEKING;
    d->last_loss = why;
    d->have_period = false;
    d->omega = 0.0f;
    d->alpha = 0.0f;
    d->phase_cam = 0xFFu;
    /* The angle frame the cam measurements were made in has just gone
     * away, so every cam measurement made in it is now worthless. Say so
     * rather than leaving a stale number for a control loop to integrate
     * against. A latched chain fault is NOT cleared here: that survives
     * until decoder_init. */
    for (u8 i = 0; i < DEC_N_CAMS; i++) {
        dec_cam_t *c = &d->cam[i];
        if (c->state != DEC_CAM_FAULT) {
            c->state = DEC_CAM_SEARCH;
        }
        c->valid = false;
        c->have_prev = false;
        c->run = 0;
        c->alive = 0;
    }
}

void decoder_init(decoder_t *d, const dec_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*d); i++) {
        ((u8 *)d)[i] = 0;
    }
    d->cfg = *cfg;
    d->teeth_per_rev = (u8)(cfg->teeth_total - cfg->teeth_missing);
    d->deg_per_tooth = 360.0f / (f32)cfg->teeth_total;
    d->state = DEC_SEEKING;
    d->phase_cam = 0xFFu;
}

/* Crank angle, in the 0..720 frame, of tooth index `tooth` on the
 * revolution given by `second`. Tooth 0 is the first tooth after the gap. */
static f32 angle_of_tooth(const decoder_t *d, u8 tooth, bool second)
{
    f32 a = d->cfg.gap_to_tdc_deg + (f32)tooth * d->deg_per_tooth;
    if (second) {
        a += 360.0f;
    }
    return tq_wrap_deg(a);
}

void decoder_on_crank_edge(decoder_t *d, tq_time_t edge_us)
{
    /* How much crank angle this edge represents. One tooth width for an
     * ordinary tooth; the gap edge covers the missing teeth as well. */
    f32 step_deg = d->deg_per_tooth;

    if (!d->have_period) {
        /* First edge after a loss: nothing to compare against yet. */
        d->last_edge = edge_us;
        d->have_period = true;
        d->last_period = 0;
        return;
    }

    u32 period = (u32)(edge_us - d->last_edge);
    if (period == 0) {
        d->noise_count++;
        return;                       /* two edges at the same timestamp */
    }

    if (d->last_period != 0) {
        f32 ratio = (f32)period / (f32)d->last_period;

        /* An edge far too early is electrical noise, not a tooth. Drop it
         * and keep the previous edge as the reference, otherwise one
         * spike destroys the period estimate for the next revolution. */
        if (ratio < d->cfg.noise_ratio) {
            d->noise_count++;
            return;
        }

        if (ratio > d->cfg.gap_ratio) {
            /* A gap. Its width says how many teeth are missing; anything
             * wider than the pattern allows means the engine stopped or
             * teeth were lost, not that we found the index. */
            f32 missing = ratio - 1.0f;
            f32 allowed = (f32)d->cfg.teeth_missing + 0.6f;
            if (missing > allowed) {
                lose_sync(d, DEC_LOSS_MISSING);
                d->last_edge = edge_us;
                d->last_period = 0;
                return;
            }
            switch (d->state) {
            case DEC_SEEKING:
                d->state = DEC_GAP_FOUND;
                d->tooth = 0;
                break;
            case DEC_GAP_FOUND:
                /* Second gap in the right place: the pattern is real. */
                d->state = DEC_CRANK_SYNC;
                d->sync_count++;
                d->tooth = 0;
                d->second_revolution = false;
                break;
            case DEC_CRANK_SYNC:
            case DEC_FULL_SYNC:
                /* The gap edge IS tooth 0, so the last ordinary tooth of a
                 * revolution is teeth_per_rev - 1. Getting this off by one
                 * makes every revolution look like a pattern fault. */
                if (d->tooth != d->teeth_per_rev - 1) {
                    /* The gap turned up somewhere it should not have. */
                    lose_sync(d, DEC_LOSS_PATTERN);
                    d->state = DEC_GAP_FOUND;
                    d->have_period = true;
                    d->tooth = 0;
                } else {
                    d->tooth = 0;
                    /* A crank revolution completed: flip which stroke we
                     * are on. Without a cam this is a guess, which is why
                     * DEC_CRANK_SYNC is not good enough for sequential. */
                    d->second_revolution = !d->second_revolution;
                }
                break;
            }
            /* Inside the gap the wheel turned (missing + 1) tooth widths,
             * so the effective per-tooth period is the gap divided by
             * that, and that is what the next prediction should use. */
            u32 eff = (u32)((f32)period / (1.0f + (f32)d->cfg.teeth_missing));
            step_deg = (1.0f + (f32)d->cfg.teeth_missing) * d->deg_per_tooth;
            d->prev_period = d->last_period;
            d->last_period = eff;
        } else {
            /* An ordinary tooth. */
            if (d->state == DEC_GAP_FOUND || d->state == DEC_CRANK_SYNC
                || d->state == DEC_FULL_SYNC) {
                d->tooth++;
                if (d->tooth >= d->teeth_per_rev) {
                    /* More teeth than the wheel has: the gap was missed. */
                    lose_sync(d, DEC_LOSS_PATTERN);
                    d->last_edge = edge_us;
                    d->last_period = period;
                    d->have_period = true;
                    return;
                }
            }
            d->prev_period = d->last_period;
            d->last_period = period;
        }
    } else {
        d->last_period = period;
    }

    /* Kinematics. omega in degrees per microsecond, alpha from how the
     * tooth period is changing -- at 7000 rpm a 4-stroke can change speed
     * measurably within one revolution, and ignoring it puts the spark a
     * degree or two late under hard acceleration. */
    if (d->last_period > 0) {
        f32 w = d->deg_per_tooth / (f32)d->last_period;
        if (d->prev_period > 0) {
            f32 w_prev = d->deg_per_tooth / (f32)d->prev_period;
            f32 dt = (f32)d->last_period;
            f32 a = (w - w_prev) / dt;
            /* Low-pass: a single mis-measured tooth must not throw the
             * acceleration estimate into the next prediction. */
            d->alpha = 0.6f * d->alpha + 0.4f * a;
        }
        d->omega = w;
    }

    /* Feed every cam's interval counter. Measuring a cam spacing by
     * counting crank teeth works with no 720-degree phase at all, which
     * is what lets the cam pattern be the thing that ESTABLISHES phase
     * rather than something that needs it first. */
    for (u8 i = 0; i < DEC_N_CAMS; i++) {
        d->cam[i].since_deg += step_deg;
    }

    d->last_edge = edge_us;
    if (d->state == DEC_CRANK_SYNC || d->state == DEC_FULL_SYNC) {
        d->angle_at_last_edge = angle_of_tooth(d, d->tooth, d->second_revolution);
    }
}

/* Crank degrees from pattern edge `i` to the next one, wrapping. These
 * spacings are fixed in the metal of the wheel: the phaser translates the
 * whole pattern, so every angle moves and no spacing does. That is the
 * entire basis of the match. */
static f32 cam_interval(const dec_cam_pattern_t *p, u8 i)
{
    u8 j = (u8)((i + 1u) % p->n_edges);
    f32 gap = p->e[j].angle_deg - p->e[i].angle_deg;
    if (gap <= 0.0f) {
        gap += TQ_CYCLE_DEG;
    }
    return gap;
}

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

/* Fold one advance measurement into this cam's per-edge residual ring. */
static void cam_accumulate(dec_cam_t *c, u8 idx, f32 adv, u8 n_edges)
{
    if (c->resid_have[idx]) {
        c->resid_sum -= c->resid[idx];
    } else {
        c->resid_have[idx] = true;
        c->resid_count++;
    }
    c->resid[idx] = adv;
    c->resid_sum += adv;
    (void)n_edges;
    c->advance_raw = adv;
    c->advance_deg = c->resid_sum / (f32)c->resid_count;
}

static void cam_drop(dec_cam_t *c)
{
    c->state = DEC_CAM_SEARCH;
    c->run = 0;
    c->alive = 0;
    c->valid = false;
}

void decoder_on_cam_edge(decoder_t *d, u8 cam, tq_time_t edge_us, bool rising)
{
    if (cam >= DEC_N_CAMS) {
        return;
    }
    const dec_cam_pattern_t *p = &d->cfg.cam[cam];
    dec_cam_t *c = &d->cam[cam];
    if (p->n_edges == 0 || p->n_edges > DEC_MAX_CAM_EDGES) {
        return;                       /* no cam fitted on this input */
    }
    if (c->state == DEC_CAM_FAULT) {
        return;                       /* latched; needs decoder_init */
    }

    /* The interval that just elapsed, and how long it took. */
    f32 since = c->since_deg;
    f32 dt_s = c->have_prev
             ? (f32)(i32)(edge_us - c->last_edge) * 1.0e-6f : 0.0f;
    c->last_edge = edge_us;
    c->since_deg = 0.0f;
    bool had_prev = c->have_prev;
    c->have_prev = true;

    /* Widen the match window by how far the phaser could have slewed
     * while the interval was being measured. The spacing itself does not
     * move, but we measure it in elapsed crank degrees, and a cam that is
     * travelling adds its own travel to that measurement. */
    f32 tol = p->match_tol_deg + p->slew_max_dps * dt_s;

    /* ---- identify which pattern edge this is ------------------------ */
    if (!had_prev) {
        /* First edge: every edge of the right polarity is a candidate. */
        c->alive = 0;
        for (u8 i = 0; i < p->n_edges; i++) {
            if (p->e[i].rising == rising) c->alive |= (u16)(1u << i);
        }
        c->state = DEC_CAM_SEARCH;
        c->run = 0;
        return;
    }

    if (c->state == DEC_CAM_LOCKED) {
        /* Fast path: we know where we were, so this is one comparison.
         * A second comparison absorbs a single dropped edge rather than
         * throwing away the lock for one missed interrupt. */
        u8 nxt = (u8)((c->idx + 1u) % p->n_edges);
        if (absf(since - cam_interval(p, c->idx)) <= tol
            && p->e[nxt].rising == rising) {
            c->idx = nxt;
        } else {
            u8 skip = (u8)((c->idx + 2u) % p->n_edges);
            f32 two = cam_interval(p, c->idx)
                    + cam_interval(p, (u8)((c->idx + 1u) % p->n_edges));
            if (absf(since - two) <= tol + p->match_tol_deg
                && p->e[skip].rising == rising) {
                c->idx = skip;        /* one edge was dropped */
                c->run = 0;
            } else {
                c->reject_run++;
                cam_drop(c);
                d->last_loss = DEC_LOSS_CAM;
                d->loss_count++;
                /* Losing the cam does not stop a running engine on the
                 * spot, but it must not keep claiming 720 phase forever
                 * either. Three consecutive rejections is about one and a
                 * half cycles: long enough not to trip on a single noisy
                 * edge, short enough to stop sequential firing before it
                 * is landing on the wrong stroke. */
                if (c->reject_run >= 3u && d->phase_cam == cam
                    && d->state == DEC_FULL_SYNC) {
                    d->state = DEC_CRANK_SYNC;
                    d->phase_cam = 0xFFu;
                }
                return;
            }
        }
    } else {
        /* Searching: keep only the candidates whose incoming spacing
         * matches what we just measured. With three unequal spacings
         * this collapses to one candidate in two edges. */
        u16 next_alive = 0;
        for (u8 i = 0; i < p->n_edges; i++) {
            if (p->e[i].rising != rising) continue;
            u8 prev = (u8)((i + p->n_edges - 1u) % p->n_edges);
            if ((c->alive & (u16)(1u << prev)) == 0u) continue;
            if (absf(since - cam_interval(p, prev)) <= tol) {
                next_alive |= (u16)(1u << i);
            }
        }
        if (next_alive == 0u) {
            /* Nothing fits. Start the walk again from this edge. */
            for (u8 i = 0; i < p->n_edges; i++) {
                if (p->e[i].rising == rising) next_alive |= (u16)(1u << i);
            }
            c->alive = next_alive;
            c->run = 0;
            return;
        }
        c->alive = next_alive;
        /* Exactly one candidate left? Then we know where we are. */
        u16 a = c->alive;
        if ((a & (u16)(a - 1u)) != 0u) {
            return;                   /* still more than one bit set */
        }
        u8 idx = 0;
        while ((a >> idx) != 1u) idx++;
        c->idx = idx;
        c->state = DEC_CAM_LOCKED;
        c->run = 0;
    }

    c->reject_run = 0;
    if (c->run < 255u) c->run++;

    /* ---- turn the identified edge into phase and advance ------------ */
    /* The crank alone cannot say which of the two revolutions we are on,
     * and the 720-frame angle already contains that answer, so using it
     * here would be circular. Build the angle the TOOTH COUNT alone
     * gives, exactly as the single-edge decoder did, and let the cam
     * choose between the two readings it is consistent with. */
    if (d->state != DEC_CRANK_SYNC && d->state != DEC_FULL_SYNC) {
        return;                       /* nothing to phase against yet */
    }
    f32 dt = (f32)(i32)(edge_us - d->last_edge);
    f32 unphased = angle_of_tooth(d, d->tooth, false)
                   + d->omega * dt + 0.5f * d->alpha * dt * dt;

    f32 obs_a = tq_wrap_deg(unphased);
    f32 obs_b = tq_wrap_deg(unphased + 360.0f);
    f32 nominal = p->e[c->idx].angle_deg;
    /* Advance is positive when the edge arrives EARLY, so it is nominal
     * minus observed. In CRANK degrees, which is twice the camshaft's own
     * movement -- the convention is crank everywhere in this file. */
    f32 adv_a = tq_angle_diff(nominal, obs_a);
    f32 adv_b = tq_angle_diff(nominal, obs_b);

    f32 lo = p->adv_min_deg - p->match_tol_deg;
    f32 hi = p->adv_max_deg + p->match_tol_deg;
    bool ok_a = (adv_a >= lo && adv_a <= hi);
    bool ok_b = (adv_b >= lo && adv_b <= hi);

    if (ok_a == ok_b) {
        /* Neither reading puts the cam inside its mechanical travel, or
         * both do. Both are refusals. "Neither" is what a jumped timing
         * chain looks like: the pattern still matches, because the wheel
         * is undamaged, but it is bodily in the wrong place. That is the
         * failure this whole design exists to catch, and it is the one
         * that bends valves, so it latches. */
        c->range_run++;
        if (c->range_run >= 3u) {
            c->state = DEC_CAM_FAULT;
            d->chain_fault = true;
            d->last_loss = DEC_LOSS_CAM;
            d->loss_count++;
            if (d->state == DEC_FULL_SYNC) {
                d->state = DEC_CRANK_SYNC;
                d->phase_cam = 0xFFu;
            }
        }
        c->valid = false;
        return;
    }

    c->range_run = 0;
    f32 adv = ok_b ? adv_b : adv_a;
    bool second = ok_b;

    /* Did it move further than oil pressure could have moved it? Compare
     * against the previous RAW sample, never against the filtered output:
     * the filter lags a real slew by design, so gating on it would fire
     * on every healthy phaser movement and cut the engine. */
    if (c->valid && dt_s > 0.0f) {
        f32 allowed = p->slew_max_dps * dt_s + p->match_tol_deg;
        if (absf(adv - c->advance_raw) > allowed) {
            c->advance_raw = adv;     /* believe it next time, not now */
            return;
        }
    }

    cam_accumulate(c, c->idx, adv, p->n_edges);
    c->valid = true;
    c->at = edge_us;

    /* Grant 720-degree phase. Never while a chain fault is latched: a
     * cam that has been caught lying does not get to hand the job to
     * its neighbour. */
    if (d->chain_fault) {
        return;
    }
    if (d->phase_cam == 0xFFu || d->phase_cam == cam) {
        d->second_revolution = second;
        d->angle_at_last_edge = angle_of_tooth(d, d->tooth,
                                               d->second_revolution);
        if (d->state == DEC_CRANK_SYNC && c->run >= 1u) {
            d->state = DEC_FULL_SYNC;
            d->phase_cam = cam;
            d->sync_count++;
        }
    }
}

bool decoder_cam_advance(const decoder_t *d, u8 cam, tq_time_t now_us,
                         f32 *advance_deg, u32 *age_us)
{
    if (cam >= DEC_N_CAMS) return false;
    const dec_cam_t *c = &d->cam[cam];
    if (!c->valid || c->state != DEC_CAM_LOCKED) return false;
    if (advance_deg) *advance_deg = c->advance_deg;
    if (age_us) *age_us = (u32)(now_us - c->at);
    return true;
}

void decoder_check_timeout(decoder_t *d, tq_time_t now_us)
{
    if (d->state == DEC_SEEKING || !d->have_period) {
        return;
    }
    /* Four tooth periods with no edge means the engine is stopping. At
     * 200 rpm on a 60-2 that is about 20 ms, which is slow enough not to
     * trip during a hard stall and fast enough to stop firing. */
    u32 limit = d->last_period ? d->last_period * 4u : 100000u;
    if (limit < 20000u) {
        limit = 20000u;
    }
    if ((u32)(now_us - d->last_edge) > limit) {
        lose_sync(d, DEC_LOSS_MISSING);
    }
}

f32 decoder_angle_at(const decoder_t *d, tq_time_t when_us)
{
    if (d->state != DEC_CRANK_SYNC && d->state != DEC_FULL_SYNC) {
        return 0.0f;
    }
    f32 dt = (f32)(i32)(when_us - d->last_edge);
    f32 a = d->angle_at_last_edge + d->omega * dt + 0.5f * d->alpha * dt * dt;
    return tq_wrap_deg(a);
}

bool decoder_time_for_angle(const decoder_t *d, tq_time_t after_us,
                            f32 angle_deg, tq_time_t *out_us)
{
    if (d->omega <= 0.0f) {
        return false;
    }
    if (d->state != DEC_FULL_SYNC && d->state != DEC_CRANK_SYNC) {
        return false;
    }

    f32 target = tq_wrap_deg(angle_deg);
    f32 now_angle = decoder_angle_at(d, after_us);
    f32 to_go = target - now_angle;
    while (to_go < 0.0f) {
        to_go += TQ_CYCLE_DEG;        /* it is next cycle, not the past */
    }

    /* Solve to_go = w*t + a*t^2/2 for t. With acceleration this is a
     * quadratic; without it, a division. Fall back to the linear answer
     * when the quadratic has no positive root, which happens when the
     * engine is decelerating hard enough to never reach the angle at the
     * current estimate -- the next tooth will correct it anyway. */
    f32 t;
    f32 w = d->omega;
    f32 a = d->alpha;
    if (a > -1e-12f && a < 1e-12f) {
        t = to_go / w;
    } else {
        f32 disc = w * w + 2.0f * a * to_go;
        if (disc < 0.0f) {
            t = to_go / w;
        } else {
            f32 root = sqrtf(disc);
            t = (-w + root) / a;
            if (t <= 0.0f) {
                t = (-w - root) / a;
            }
            if (t <= 0.0f) {
                t = to_go / w;
            }
        }
    }
    if (t < 0.0f) {
        return false;
    }
    *out_us = after_us + (tq_time_t)t;
    return true;
}

f32 decoder_rpm(const decoder_t *d)
{
    if (!d->have_period || d->last_period == 0) {
        return 0.0f;
    }
    /* deg/us -> rpm: omega * 1e6 us/s * 60 s/min / 360 deg/rev */
    return d->omega * 1.0e6f * 60.0f / 360.0f;
}
