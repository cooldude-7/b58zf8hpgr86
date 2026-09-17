#include "cal.h"

#include <string.h>

/* Standard CRC-32 (the zlib/PNG one), so the Python side can use
 * zlib.crc32 and get the same answer with no special code. */
u32 tq_crc32(u32 crc, const void *data, u32 len)
{
    const u8 *p = (const u8 *)data;
    crc = ~crc;
    for (u32 i = 0; i < len; i++) {
        crc ^= p[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320u & (u32)(-(i32)(crc & 1u)));
        }
    }
    return ~crc;
}

void cal_init(cal_t *c)
{
    memset(c, 0, sizeof(*c));
}

int cal_index(const cal_t *c, const char *key)
{
    for (u8 i = 0; i < c->n_tables; i++) {
        if (!strncmp(c->t[i].key, key, CAL_NAME_LEN)) {
            return (int)i;
        }
    }
    return -1;
}

cal_table_t *cal_find(cal_t *c, const char *key)
{
    int i = cal_index(c, key);
    return i < 0 ? 0 : &c->t[i];
}

static void locate(const f32 *axis, u8 n, f32 v, u8 *idx, f32 *frac)
{
    if (!(v == v)) {                  /* NaN in, first cell out */
        *idx = 0; *frac = 0.0f; return;
    }
    if (v <= axis[0]) {
        *idx = 0; *frac = 0.0f; return;
    }
    if (v >= axis[n - 1]) {
        *idx = (u8)(n - 2); *frac = 1.0f; return;
    }
    u8 i = 0;
    while (i + 2 < n && axis[i + 1] <= v) {
        i++;
    }
    f32 span = axis[i + 1] - axis[i];
    *idx = i;
    *frac = span > 0.0f ? (v - axis[i]) / span : 0.0f;
}

f32 cal_lookup(const cal_table_t *t, f32 xv, f32 yv)
{
    u8 i, j;
    f32 fx, fy;
    locate(t->x, t->n_x, xv, &i, &fx);
    locate(t->y, t->n_y, yv, &j, &fy);
    f32 top = t->v[j][i] * (1.0f - fx) + t->v[j][i + 1] * fx;
    f32 bot = t->v[j + 1][i] * (1.0f - fx) + t->v[j + 1][i + 1] * fx;
    return top * (1.0f - fy) + bot * fy;
}

bool cal_set_cell(cal_table_t *t, u8 j, u8 i, f32 value)
{
    if (j >= t->n_y || i >= t->n_x) {
        return false;
    }
    if (!(value == value)) {
        return false;                 /* NaN is not a calibration value */
    }
    if (value < t->lo || value > t->hi) {
        return false;
    }
    t->v[j][i] = value;
    return true;
}

u32 cal_crc(const cal_table_t *t)
{
    u32 crc = 0;
    crc = tq_crc32(crc, t->key, (u32)strlen(t->key));
    crc = tq_crc32(crc, t->x, (u32)t->n_x * sizeof(f32));
    crc = tq_crc32(crc, t->y, (u32)t->n_y * sizeof(f32));
    /* row by row: the storage is a fixed-width array, but only the used
     * part of each row is part of the image */
    for (u8 j = 0; j < t->n_y; j++) {
        crc = tq_crc32(crc, t->v[j], (u32)t->n_x * sizeof(f32));
    }
    return crc;
}
