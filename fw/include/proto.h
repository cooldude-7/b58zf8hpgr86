/* The tuner link protocol.
 *
 * One framing for USB-CDC and for CAN-FD payloads, because the tuner
 * should not care which wire it is on.
 *
 *   A5 5A  cmd  len_lo len_hi  payload...  crc_lo crc_hi
 *
 * Little-endian throughout. The CRC is CRC-16/CCITT over cmd, length and
 * payload. A frame with a bad CRC is dropped silently, not answered: an
 * ECU that replies to corrupted frames is an ECU that can be talked into
 * anything by a noisy cable.
 *
 * Every reply carries a status byte first. There are no fire-and-forget
 * writes: a write the tuner cannot confirm is a write it must not show
 * as having happened.
 */
#ifndef TQ_PROTO_H
#define TQ_PROTO_H

#include "cal.h"
#include "chan.h"
#include "tq_types.h"

#define PROTO_SYNC0 0xA5u
#define PROTO_SYNC1 0x5Au
#define PROTO_VERSION 1u
#define PROTO_MAX_PAYLOAD 1024u

typedef enum {
    CMD_IDENTIFY = 0x01,
    CMD_DESCRIBE = 0x02,      /* payload: table index */
    CMD_READ_TABLE = 0x03,    /* payload: table index */
    CMD_WRITE_CELL = 0x04,    /* payload: idx, j, i, f32 */
    CMD_WRITE_TABLE = 0x05,   /* payload: idx, n_x, n_y, x[], y[], v[] */
    CMD_BURN = 0x06,
    CMD_TABLE_CRC = 0x07,     /* payload: table index */
    CMD_CHANNELS = 0x08       /* payload: one sub-op byte, below */
} proto_cmd_t;

/* CMD_CHANNELS carries a sub-op rather than being two commands, because
 * the list and the values have to come from the same table or the tuner
 * ends up plotting one firmware's numbers under another's names.
 *
 *   CH_OP_DESCRIBE -> count u8, hash u32, count x 16-byte name
 *   CH_OP_VALUES   -> count u8, hash u32, count x f32
 *
 * The hash is in both replies on purpose: a tuner that reconnects to a
 * reflashed ECU mid-session finds out on the next poll rather than on
 * the next time someone looks at a gauge and disbelieves it. */
typedef enum {
    CH_OP_DESCRIBE = 0x00,
    CH_OP_VALUES = 0x01
} proto_chan_op_t;

typedef enum {
    ST_OK = 0x00,
    ST_BAD_CMD = 0x01,
    ST_BAD_LEN = 0x02,
    ST_NO_TABLE = 0x03,
    ST_OUT_OF_RANGE = 0x04,
    ST_BAD_VALUE = 0x05,
    ST_LAYOUT = 0x06,
    ST_NOT_ALLOWED = 0x07
} proto_status_t;

typedef struct {
    u8 buf[PROTO_MAX_PAYLOAD + 16];
    u32 have;
    cal_t *cal;
    cal_t *flash;
    /* Read-only, and const for the same reason the monitor's inputs are:
     * the tuner link may watch the engine and may write calibration, and
     * it may never reach into running state. */
    const ecu_signals_t *sig;
    u32 frames_ok;
    u32 frames_bad_crc;
    u32 frames_dropped;
} proto_t;

void proto_init(proto_t *p, cal_t *ram, cal_t *flash);

/* Point the link at the running engine's signals. Without this
 * CMD_CHANNELS answers ST_NOT_ALLOWED rather than a block of zeroes,
 * because a gauge reading zero and a gauge reading nothing look the
 * same on screen and are not the same thing. */
void proto_set_signals(proto_t *p, const ecu_signals_t *sig);

/* Feed received bytes. Whenever a complete valid frame is decoded, the
 * reply is written to `out` and its length returned; 0 means nothing to
 * send yet. */
u32 proto_feed(proto_t *p, const u8 *data, u32 len, u8 *out, u32 out_cap);

u16 proto_crc16(const u8 *data, u32 len);
u32 proto_frame(u8 cmd, const u8 *payload, u32 len, u8 *out, u32 out_cap);

#endif /* TQ_PROTO_H */
