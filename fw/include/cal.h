/* Calibration store: the tables the ECU runs on, in the ECU.
 *
 * Fixed layout, sized at compile time. A tuner may change the numbers in
 * a table and move its breakpoints; it may not change how many there
 * are, because the ECU's memory map is fixed and a table that grows at
 * run time is a table that overruns something.
 *
 * Values are single precision, which is what the CRC is computed over on
 * both sides. Checking a CRC over what the tuner meant to send rather
 * than what the ECU can hold would fail on every value that is not
 * exactly representable.
 */
#ifndef TQ_CAL_H
#define TQ_CAL_H

#include "tq_types.h"

#define CAL_MAX_X 24
#define CAL_MAX_Y 20
#define CAL_MAX_TABLES 8
#define CAL_NAME_LEN 16

typedef struct {
    char key[CAL_NAME_LEN];
    u8 n_x, n_y;
    f32 lo, hi;
    f32 x[CAL_MAX_X];
    f32 y[CAL_MAX_Y];
    f32 v[CAL_MAX_Y][CAL_MAX_X];
} cal_table_t;

typedef struct {
    cal_table_t t[CAL_MAX_TABLES];
    u8 n_tables;
} cal_t;

void cal_init(cal_t *c);
cal_table_t *cal_find(cal_t *c, const char *key);
int cal_index(const cal_t *c, const char *key);

/* Bilinear lookup, clamped to the axis range -- identical in behaviour to
 * Table.lookup in the Python. */
f32 cal_lookup(const cal_table_t *t, f32 xv, f32 yv);

bool cal_set_cell(cal_table_t *t, u8 j, u8 i, f32 value);

/* CRC32 over key, axes and values as little-endian float32, matching
 * Table.crc() in the Python exactly. */
u32 cal_crc(const cal_table_t *t);
u32 tq_crc32(u32 crc, const void *data, u32 len);

#endif /* TQ_CAL_H */
