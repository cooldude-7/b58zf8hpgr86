/* The live channel list: what the tuner is allowed to watch.
 *
 * A gauge that reads a number the ECU never computed is worse than no
 * gauge, so this is a table rather than a pile of accessors -- one place
 * that says which signals exist, what they are called and what units
 * they leave in. The tuner learns the list from the ECU at connect and
 * does not carry a copy of it, which is the only way the two stay in
 * step across a firmware change.
 *
 * The names match the keys the tuner already uses for the simulator, so
 * the same gauges work against either. Anything this ECU has that the
 * simulator does not is still sent; a tuner that does not recognise a
 * name just holds it in the dictionary.
 */
#ifndef TQ_CHAN_H
#define TQ_CHAN_H

#include "ecu.h"
#include "tq_types.h"

/* Fixed width on the wire, so the tuner can index rather than parse. */
#define CHAN_NAME_LEN 16

typedef enum {
    CH_F32 = 0,
    CH_I32,          /* enums, which C sizes as int */
    CH_U32,
    CH_U16,
    CH_U8,
    CH_BOOL
} chan_type_t;

typedef struct {
    const char *key;
    u16 off;         /* byte offset into ecu_signals_t */
    u8 type;
    f32 scale;       /* value = raw * scale + bias */
    f32 bias;
} chan_desc_t;

u8 chan_count(void);
const chan_desc_t *chan_at(u8 i);

/* The channel's value in the unit its name implies -- degrees Celsius,
 * psi of boost, milliseconds -- not the raw signal. The conversion
 * belongs here because the ECU is the only thing that knows what it
 * stored. */
f32 chan_value(const ecu_signals_t *s, u8 i);

/* A hash over the names, in order. The tuner compares it against what
 * it was told at connect, so a firmware that gained a channel cannot
 * quietly shift every gauge one place to the left. */
u32 chan_hash(void);

#endif /* TQ_CHAN_H */
