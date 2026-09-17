#include "proto.h"

#include <string.h>

u16 proto_crc16(const u8 *data, u32 len)
{
    u16 crc = 0xFFFFu;
    for (u32 i = 0; i < len; i++) {
        crc ^= (u16)((u16)data[i] << 8);
        for (int b = 0; b < 8; b++) {
            crc = (u16)((crc & 0x8000u) ? (((u32)crc << 1) ^ 0x1021u) : ((u32)crc << 1));
        }
    }
    return crc;
}

void proto_init(proto_t *p, cal_t *ram, cal_t *flash)
{
    memset(p, 0, sizeof(*p));
    p->cal = ram;
    p->flash = flash;
}

u32 proto_frame(u8 cmd, const u8 *payload, u32 len, u8 *out, u32 out_cap)
{
    if (len > PROTO_MAX_PAYLOAD || out_cap < len + 7u) {
        return 0;
    }
    out[0] = PROTO_SYNC0;
    out[1] = PROTO_SYNC1;
    out[2] = cmd;
    out[3] = (u8)(len & 0xFFu);
    out[4] = (u8)(len >> 8);
    if (len) {
        memcpy(out + 5, payload, len);
    }
    u16 crc = proto_crc16(out + 2, len + 3u);
    out[5 + len] = (u8)(crc & 0xFFu);
    out[6 + len] = (u8)(crc >> 8);
    return len + 7u;
}

static u32 reply(u8 cmd, u8 status, const u8 *body, u32 body_len,
                 u8 *out, u32 out_cap)
{
    u8 payload[PROTO_MAX_PAYLOAD];
    if (body_len + 1u > sizeof(payload)) {
        return 0;
    }
    payload[0] = status;
    if (body_len) {
        memcpy(payload + 1, body, body_len);
    }
    return proto_frame(cmd, payload, body_len + 1u, out, out_cap);
}

static void put_f32(u8 *dst, f32 v)
{
    memcpy(dst, &v, sizeof(f32));
}

static f32 get_f32(const u8 *src)
{
    f32 v;
    memcpy(&v, src, sizeof(f32));
    return v;
}

static u32 handle(proto_t *p, u8 cmd, const u8 *pl, u32 len,
                  u8 *out, u32 out_cap)
{
    u8 body[PROTO_MAX_PAYLOAD];

    switch (cmd) {
    case CMD_IDENTIFY: {
        /* version, table count, then a fixed-width id string */
        body[0] = PROTO_VERSION;
        body[1] = p->cal->n_tables;
        memset(body + 2, 0, 16);
        memcpy(body + 2, "TORQUETUNE-FW", 13);
        /* a hash of the layout, so the tuner can refuse a tune that does
         * not fit this ECU before sending a single cell */
        u32 h = 0;
        for (u8 i = 0; i < p->cal->n_tables; i++) {
            const cal_table_t *t = &p->cal->t[i];
            h = tq_crc32(h, t->key, (u32)strlen(t->key));
            u8 dims[2] = { t->n_x, t->n_y };
            h = tq_crc32(h, dims, 2);
        }
        memcpy(body + 18, &h, 4);
        return reply(cmd, ST_OK, body, 22, out, out_cap);
    }

    case CMD_DESCRIBE: {
        if (len != 1) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        if (pl[0] >= p->cal->n_tables)
            return reply(cmd, ST_NO_TABLE, 0, 0, out, out_cap);
        const cal_table_t *t = &p->cal->t[pl[0]];
        memset(body, 0, CAL_NAME_LEN);
        memcpy(body, t->key, strlen(t->key));
        body[CAL_NAME_LEN] = t->n_x;
        body[CAL_NAME_LEN + 1] = t->n_y;
        put_f32(body + CAL_NAME_LEN + 2, t->lo);
        put_f32(body + CAL_NAME_LEN + 6, t->hi);
        return reply(cmd, ST_OK, body, CAL_NAME_LEN + 10u, out, out_cap);
    }

    case CMD_READ_TABLE: {
        if (len != 1) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        if (pl[0] >= p->cal->n_tables)
            return reply(cmd, ST_NO_TABLE, 0, 0, out, out_cap);
        const cal_table_t *t = &p->cal->t[pl[0]];
        u32 n = 0;
        body[n++] = t->n_x;
        body[n++] = t->n_y;
        for (u8 i = 0; i < t->n_x; i++) { put_f32(body + n, t->x[i]); n += 4; }
        for (u8 j = 0; j < t->n_y; j++) { put_f32(body + n, t->y[j]); n += 4; }
        for (u8 j = 0; j < t->n_y; j++) {
            for (u8 i = 0; i < t->n_x; i++) { put_f32(body + n, t->v[j][i]); n += 4; }
        }
        return reply(cmd, ST_OK, body, n, out, out_cap);
    }

    case CMD_WRITE_CELL: {
        if (len != 7) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        if (pl[0] >= p->cal->n_tables)
            return reply(cmd, ST_NO_TABLE, 0, 0, out, out_cap);
        cal_table_t *t = &p->cal->t[pl[0]];
        u8 j = pl[1], i = pl[2];
        if (j >= t->n_y || i >= t->n_x)
            return reply(cmd, ST_OUT_OF_RANGE, 0, 0, out, out_cap);
        f32 v = get_f32(pl + 3);
        if (!cal_set_cell(t, j, i, v))
            return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
        /* Echo the committed value back. The tuner marks the cell as
         * being in RAM on this echo and never on the keystroke. */
        put_f32(body, t->v[j][i]);
        return reply(cmd, ST_OK, body, 4, out, out_cap);
    }

    case CMD_WRITE_TABLE: {
        if (len < 3) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        if (pl[0] >= p->cal->n_tables)
            return reply(cmd, ST_NO_TABLE, 0, 0, out, out_cap);
        cal_table_t *t = &p->cal->t[pl[0]];
        u8 nx = pl[1], ny = pl[2];
        /* The ECU's layout is fixed. A tune of a different shape is
         * refused outright rather than truncated to fit. */
        if (nx != t->n_x || ny != t->n_y)
            return reply(cmd, ST_LAYOUT, 0, 0, out, out_cap);
        u32 need = 3u + 4u * ((u32)nx + ny + (u32)nx * ny);
        if (len != need) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);

        /* Validate everything BEFORE storing any of it: a table left
         * half written is worse than one not written at all. */
        const u8 *q = pl + 3;
        f32 prev = 0.0f;
        for (u8 i = 0; i < nx; i++) {
            f32 v = get_f32(q + 4u * i);
            if (!(v == v)) return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
            if (i && !(v > prev)) return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
            prev = v;
        }
        const u8 *qy = q + 4u * nx;
        for (u8 j = 0; j < ny; j++) {
            f32 v = get_f32(qy + 4u * j);
            if (!(v == v)) return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
            if (j && !(v > prev)) return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
            prev = v;
        }
        const u8 *qv = qy + 4u * ny;
        for (u32 k = 0; k < (u32)nx * ny; k++) {
            f32 v = get_f32(qv + 4u * k);
            if (!(v == v) || v < t->lo || v > t->hi)
                return reply(cmd, ST_BAD_VALUE, 0, 0, out, out_cap);
        }

        for (u8 i = 0; i < nx; i++) t->x[i] = get_f32(q + 4u * i);
        for (u8 j = 0; j < ny; j++) t->y[j] = get_f32(qy + 4u * j);
        for (u8 j = 0; j < ny; j++) {
            for (u8 i = 0; i < nx; i++) {
                t->v[j][i] = get_f32(qv + 4u * ((u32)j * nx + i));
            }
        }
        u32 crc = cal_crc(t);
        memcpy(body, &crc, 4);
        return reply(cmd, ST_OK, body, 4, out, out_cap);
    }

    case CMD_BURN: {
        if (len != 0) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        *p->flash = *p->cal;
        u32 n = 0;
        body[n++] = p->flash->n_tables;
        for (u8 i = 0; i < p->flash->n_tables; i++) {
            u32 crc = cal_crc(&p->flash->t[i]);
            memcpy(body + n, &crc, 4);
            n += 4;
        }
        return reply(cmd, ST_OK, body, n, out, out_cap);
    }

    case CMD_TABLE_CRC: {
        if (len != 1) return reply(cmd, ST_BAD_LEN, 0, 0, out, out_cap);
        if (pl[0] >= p->cal->n_tables)
            return reply(cmd, ST_NO_TABLE, 0, 0, out, out_cap);
        u32 crc = cal_crc(&p->cal->t[pl[0]]);
        memcpy(body, &crc, 4);
        return reply(cmd, ST_OK, body, 4, out, out_cap);
    }

    default:
        return reply(cmd, ST_BAD_CMD, 0, 0, out, out_cap);
    }
}

u32 proto_feed(proto_t *p, const u8 *data, u32 len, u8 *out, u32 out_cap)
{
    for (u32 k = 0; k < len; k++) {
        if (p->have < sizeof(p->buf)) {
            p->buf[p->have++] = data[k];
        } else {
            p->have = 0;
            p->frames_dropped++;
        }
    }

    for (;;) {
        /* Resynchronise: drop bytes until a start marker. A link that
         * comes up mid-frame must recover on its own. */
        u32 start = 0;
        while (start + 1 < p->have
               && !(p->buf[start] == PROTO_SYNC0 && p->buf[start + 1] == PROTO_SYNC1)) {
            start++;
        }
        if (start) {
            memmove(p->buf, p->buf + start, p->have - start);
            p->have -= start;
            p->frames_dropped++;
        }
        if (p->have < 7) {
            return 0;
        }
        u32 plen = (u32)p->buf[3] | ((u32)p->buf[4] << 8);
        if (plen > PROTO_MAX_PAYLOAD) {
            p->buf[0] = 0;              /* not a real frame: resync past it */
            p->frames_bad_crc++;
            continue;
        }
        u32 total = plen + 7u;
        if (p->have < total) {
            return 0;
        }
        u16 want = (u16)p->buf[5 + plen] | (u16)((u16)p->buf[6 + plen] << 8);
        u16 got = proto_crc16(p->buf + 2, plen + 3u);
        u8 cmd = p->buf[2];
        u32 n = 0;
        if (want == got) {
            p->frames_ok++;
            n = handle(p, cmd, p->buf + 5, plen, out, out_cap);
        } else {
            /* Dropped, not answered. Replying to a corrupted frame lets a
             * noisy cable steer the ECU. */
            p->frames_bad_crc++;
        }
        memmove(p->buf, p->buf + total, p->have - total);
        p->have -= total;
        if (n) {
            return n;
        }
    }
}
