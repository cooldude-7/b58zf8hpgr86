#include "decoder.h"

#include <math.h>

dec_config_t decoder_config_b48(void)
{
    /* PROVISIONAL. 60-2 is the usual BMW crank wheel and the cam window is
     * a placeholder. Both must be replaced with scope measurements before
     * this runs an engine -- see docs/ultracode-plan.md, Phase E gates. */
    dec_config_t c;
    c.teeth_total = 60;
    c.teeth_missing = 2;
    c.gap_ratio = 1.6f;
    c.noise_ratio = 0.45f;
    c.gap_to_tdc_deg = 114.0f;
    c.cam_edge_angle_deg = 90.0f;
    c.cam_tolerance_deg = 25.0f;
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
    d->cam_seen = false;
    d->omega = 0.0f;
    d->alpha = 0.0f;
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

    d->last_edge = edge_us;
    if (d->state == DEC_CRANK_SYNC || d->state == DEC_FULL_SYNC) {
        d->angle_at_last_edge = angle_of_tooth(d, d->tooth, d->second_revolution);
    }
}

void decoder_on_cam_edge(decoder_t *d, tq_time_t edge_us)
{
    d->cam_edge = edge_us;
    d->cam_seen = true;

    if (d->state != DEC_CRANK_SYNC && d->state != DEC_FULL_SYNC) {
        return;                       /* nothing to phase against yet */
    }

    /* The cam fires once per cycle at a known angle, so seeing it tells
     * us outright which revolution we are on.
     *
     * Deciding that from the 720-degree angle would be circular -- that
     * angle already contains the phase we are trying to establish. So we
     * build the angle the tooth count alone gives us, with no phase
     * applied, and ask which of the two possible readings puts the cam
     * where the configuration says it is.
     *
     * The cam runs off a VANOS phaser, so its position moves with cam
     * timing; the tolerance has to cover the phaser's full authority or
     * the cam will be disbelieved every time it advances. */
    f32 dt = (f32)(i32)(edge_us - d->last_edge);
    f32 unphased = angle_of_tooth(d, d->tooth, false)
                   + d->omega * dt + 0.5f * d->alpha * dt * dt;

    /* Distance to the configured cam angle, in the 720 frame. Near zero
     * means this reading is already right; near 360 means the engine is
     * one revolution further on than the unphased reading says. */
    f32 gap720 = tq_angle_diff(unphased, d->cfg.cam_edge_angle_deg);
    f32 mag = gap720 < 0.0f ? -gap720 : gap720;
    bool should_be_second = (mag > 180.0f);

    /* Now the tolerance check, in the 360 frame where phase cannot
     * confuse it: is the cam anywhere near where it belongs at all? */
    f32 off = mag;
    if (should_be_second) {
        off = 360.0f - off;
    }
    if (off > d->cfg.cam_tolerance_deg) {
        /* The cam is not where the crank says it should be: a wiring
         * fault, the wrong pattern, or a jumped chain. Do not use it, and
         * do not claim phase on it. */
        d->last_loss = DEC_LOSS_CAM;
        d->loss_count++;
        return;
    }

    d->second_revolution = should_be_second;
    d->angle_at_last_edge = angle_of_tooth(d, d->tooth, d->second_revolution);
    if (d->state == DEC_CRANK_SYNC) {
        d->state = DEC_FULL_SYNC;
        d->sync_count++;
    }
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
