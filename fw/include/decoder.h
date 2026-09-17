/* Crank and cam decoder: turns tooth edges into engine position.
 *
 * Nothing else in the firmware may guess where the engine is. Spark,
 * injection and pump timing all ask this module, and it is the only place
 * allowed to say "I do not know", which is the answer that keeps the
 * engine from being fired at a random angle during cranking.
 *
 * Pattern: an N-minus-M missing-tooth crank wheel (60-2 on most BMW
 * engines) plus a cam signal for 720-degree phase. The exact B48 crank
 * tooth count and the VANOS cam target-wheel patterns must be confirmed
 * from a scope capture before this drives a real engine; the numbers in
 * decoder_config_b48() are a starting point, not a measurement.
 */
#ifndef TQ_DECODER_H
#define TQ_DECODER_H

#include "tq_types.h"

typedef enum {
    DEC_SEEKING = 0,   /* no idea where the engine is */
    DEC_GAP_FOUND,     /* one candidate gap seen, not yet confirmed */
    DEC_CRANK_SYNC,    /* crank position known, but not which stroke */
    DEC_FULL_SYNC      /* 720-degree phase known: sequential is allowed */
} dec_state_t;

typedef enum {
    DEC_LOSS_NONE = 0,
    DEC_LOSS_NOISE,        /* a tooth arrived far too early */
    DEC_LOSS_MISSING,      /* teeth stopped arriving */
    DEC_LOSS_PATTERN,      /* the gap turned up where it should not */
    DEC_LOSS_CAM           /* cam disagreed with the crank */
} dec_loss_t;

typedef struct {
    u8 teeth_total;        /* teeth on a full wheel if none were missing (60) */
    u8 teeth_missing;      /* how many are ground off (2) */
    f32 gap_ratio;         /* period ratio that counts as the gap (~1.5) */
    f32 noise_ratio;       /* period ratio below which an edge is noise (~0.4) */
    /* Crank angle of the first tooth AFTER the gap, in degrees BTDC of
     * cylinder 1 compression. Measured with a timing light, not guessed. */
    f32 gap_to_tdc_deg;
    /* Where in the 720-degree cycle the cam edge occurs, and how far off
     * it may be before the cam is disbelieved. This is what gives phase:
     * the crank alone cannot tell compression from exhaust. */
    f32 cam_edge_angle_deg;      /* 0..720 */
    f32 cam_tolerance_deg;
} dec_config_t;

typedef struct {
    dec_config_t cfg;

    dec_state_t state;
    dec_loss_t last_loss;

    /* tooth bookkeeping */
    u8 tooth;              /* index since the gap, 0 = first tooth after it */
    u8 teeth_per_rev;      /* teeth_total - teeth_missing */
    f32 deg_per_tooth;

    /* timing */
    tq_time_t last_edge;
    u32 last_period;       /* microseconds between the last two teeth */
    u32 prev_period;
    bool have_period;

    /* kinematics, in degrees per microsecond */
    f32 omega;
    f32 alpha;             /* deg/us^2 */
    f32 angle_at_last_edge;/* crank angle (0..720) at last_edge */

    /* phase */
    bool second_revolution;/* true when we are in 360..720 */
    bool cam_seen;
    tq_time_t cam_edge;

    /* diagnostics */
    u32 sync_count;
    u32 loss_count;
    u32 noise_count;
} decoder_t;

void decoder_init(decoder_t *d, const dec_config_t *cfg);
dec_config_t decoder_config_b48(void);

/* Call from the crank input-capture ISR. */
void decoder_on_crank_edge(decoder_t *d, tq_time_t edge_us);

/* Call from the cam input-capture ISR. */
void decoder_on_cam_edge(decoder_t *d, tq_time_t edge_us);

/* Call from the slow task: declares sync lost if the engine has stopped. */
void decoder_check_timeout(decoder_t *d, tq_time_t now_us);

static inline bool decoder_has_phase(const decoder_t *d)
{
    return d->state == DEC_FULL_SYNC;
}

/* Predicted crank angle (0..720 BTDC-referenced) at a given time. */
f32 decoder_angle_at(const decoder_t *d, tq_time_t when_us);

/* When the engine will next reach this angle. Returns false if the engine
 * is not turning or the angle is already behind us by more than a cycle. */
bool decoder_time_for_angle(const decoder_t *d, tq_time_t after_us,
                            f32 angle_deg, tq_time_t *out_us);

f32 decoder_rpm(const decoder_t *d);

#endif /* TQ_DECODER_H */
