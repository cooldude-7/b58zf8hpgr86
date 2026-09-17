/* Framing and command handling, including the ways a link misbehaves. */
#include <string.h>

#include "proto.h"
#include "tq_test.h"

static cal_t ram, flash;
static proto_t p;
static u8 out[PROTO_MAX_PAYLOAD + 64];

static void setup(void)
{
    cal_init(&ram);
    ram.n_tables = 1;
    cal_table_t *t = &ram.t[0];
    memset(t, 0, sizeof(*t));
    strcpy(t->key, "ve");
    t->n_x = 4; t->n_y = 3;
    t->lo = 0.05f; t->hi = 2.0f;
    for (u8 i = 0; i < 4; i++) t->x[i] = 1000.0f * (f32)(i + 1);
    for (u8 j = 0; j < 3; j++) t->y[j] = 50.0f * (f32)(j + 1);
    for (u8 j = 0; j < 3; j++)
        for (u8 i = 0; i < 4; i++) t->v[j][i] = 0.8f;
    flash = ram;
    proto_init(&p, &ram, &flash);
}

static u32 send(u8 cmd, const u8 *pl, u32 len)
{
    u8 frame[PROTO_MAX_PAYLOAD + 16];
    u32 n = proto_frame(cmd, pl, len, frame, sizeof(frame));
    return proto_feed(&p, frame, n, out, sizeof(out));
}

/* byte at a time, the way a real UART delivers */
static u32 send_dribbled(u8 cmd, const u8 *pl, u32 len)
{
    u8 frame[PROTO_MAX_PAYLOAD + 16];
    u32 n = proto_frame(cmd, pl, len, frame, sizeof(frame));
    u32 got = 0;
    for (u32 i = 0; i < n; i++) {
        u32 r = proto_feed(&p, frame + i, 1, out, sizeof(out));
        if (r) got = r;
    }
    return got;
}

int main(void)
{
    TQ_CASE("identify");
    setup();
    {
        u32 n = send(CMD_IDENTIFY, 0, 0);
        TQ_CHECK(n > 0, "no reply");
        TQ_CHECK(out[2] == CMD_IDENTIFY, "wrong command echoed");
        TQ_CHECK(out[5] == ST_OK, "status %d", out[5]);
        TQ_CHECK(out[6] == PROTO_VERSION, "version %d", out[6]);
        TQ_CHECK(out[7] == 1, "table count %d", out[7]);
        TQ_PASS("identify");
    }

    TQ_CASE("a frame delivered one byte at a time still works");
    setup();
    TQ_CHECK(send_dribbled(CMD_IDENTIFY, 0, 0) > 0, "no reply when dribbled");
    TQ_PASS("byte-at-a-time framing");

    TQ_CASE("write a cell and read it back");
    setup();
    {
        u8 pl[7] = { 0, 1, 2, 0, 0, 0, 0 };
        f32 v = 1.25f;
        memcpy(pl + 3, &v, 4);
        u32 n = send(CMD_WRITE_CELL, pl, 7);
        TQ_CHECK(n > 0 && out[5] == ST_OK, "write refused, status %d", out[5]);
        f32 echoed;
        memcpy(&echoed, out + 6, 4);
        TQ_NEAR(echoed, 1.25f, 1e-6, "echo");
        TQ_NEAR(ram.t[0].v[1][2], 1.25f, 1e-6, "stored value");
        TQ_PASS("write cell");
    }

    TQ_CASE("out of range values and indices are refused");
    setup();
    {
        u8 pl[7] = { 0, 1, 2, 0, 0, 0, 0 };
        f32 bad = 99.0f;
        memcpy(pl + 3, &bad, 4);
        send(CMD_WRITE_CELL, pl, 7);
        TQ_CHECK(out[5] == ST_BAD_VALUE, "status %d for an out-of-range value", out[5]);

        u8 nan_bytes[4] = { 0x00, 0x00, 0xC0, 0x7F };     /* quiet NaN */
        memcpy(pl + 3, nan_bytes, 4);
        send(CMD_WRITE_CELL, pl, 7);
        TQ_CHECK(out[5] == ST_BAD_VALUE, "status %d for NaN", out[5]);

        u8 pl2[7] = { 0, 99, 0, 0, 0, 0, 0 };
        f32 ok = 1.0f;
        memcpy(pl2 + 3, &ok, 4);
        send(CMD_WRITE_CELL, pl2, 7);
        TQ_CHECK(out[5] == ST_OUT_OF_RANGE, "status %d for a bad index", out[5]);

        u8 pl3[7] = { 7, 0, 0, 0, 0, 0, 0 };
        send(CMD_WRITE_CELL, pl3, 7);
        TQ_CHECK(out[5] == ST_NO_TABLE, "status %d for a bad table", out[5]);
        TQ_PASS("bad writes refused");
    }

    TQ_CASE("a table of the wrong shape is refused outright");
    setup();
    {
        u8 pl[3 + 4 * (3 + 2 + 6)];
        memset(pl, 0, sizeof(pl));
        pl[0] = 0; pl[1] = 3; pl[2] = 2;          /* ECU has 4x3 */
        send(CMD_WRITE_TABLE, pl, sizeof(pl));
        TQ_CHECK(out[5] == ST_LAYOUT, "status %d", out[5]);
        TQ_PASS("fixed layout enforced");
    }

    TQ_CASE("a table write is all or nothing");
    setup();
    {
        f32 before = ram.t[0].v[0][0];
        u32 n = 3 + 4 * (4 + 3 + 12);
        u8 pl[3 + 4 * (4 + 3 + 12)];
        memset(pl, 0, sizeof(pl));
        pl[0] = 0; pl[1] = 4; pl[2] = 3;
        u32 o = 3;
        for (int i = 0; i < 4; i++) { f32 v = 1000.0f * (i + 1); memcpy(pl + o, &v, 4); o += 4; }
        for (int j = 0; j < 3; j++) { f32 v = 50.0f * (j + 1); memcpy(pl + o, &v, 4); o += 4; }
        for (int k = 0; k < 12; k++) {
            f32 v = (k == 11) ? 50.0f : 0.9f;     /* the last one is illegal */
            memcpy(pl + o, &v, 4); o += 4;
        }
        send(CMD_WRITE_TABLE, pl, n);
        TQ_CHECK(out[5] == ST_BAD_VALUE, "status %d", out[5]);
        TQ_NEAR(ram.t[0].v[0][0], before, 1e-9,
                "a refused table write changed the ECU anyway");
        TQ_PASS("no partial writes");
    }

    TQ_CASE("non-monotonic axes are refused");
    setup();
    {
        u32 n = 3 + 4 * (4 + 3 + 12);
        u8 pl[3 + 4 * (4 + 3 + 12)];
        memset(pl, 0, sizeof(pl));
        pl[0] = 0; pl[1] = 4; pl[2] = 3;
        u32 o = 3;
        f32 xs[4] = { 1000.0f, 3000.0f, 2000.0f, 4000.0f };   /* out of order */
        for (int i = 0; i < 4; i++) { memcpy(pl + o, &xs[i], 4); o += 4; }
        for (int j = 0; j < 3; j++) { f32 v = 50.0f * (j + 1); memcpy(pl + o, &v, 4); o += 4; }
        for (int k = 0; k < 12; k++) { f32 v = 0.9f; memcpy(pl + o, &v, 4); o += 4; }
        send(CMD_WRITE_TABLE, pl, n);
        TQ_CHECK(out[5] == ST_BAD_VALUE, "status %d", out[5]);
        TQ_PASS("axis order enforced");
    }

    TQ_CASE("burn reports a CRC over what was committed");
    setup();
    {
        u8 pl[7] = { 0, 0, 0, 0, 0, 0, 0 };
        f32 v = 1.1f;
        memcpy(pl + 3, &v, 4);
        send(CMD_WRITE_CELL, pl, 7);
        send(CMD_BURN, 0, 0);
        TQ_CHECK(out[5] == ST_OK, "burn status %d", out[5]);
        TQ_CHECK(out[6] == 1, "table count %d", out[6]);
        u32 crc;
        memcpy(&crc, out + 7, 4);
        TQ_CHECK(crc == cal_crc(&flash.t[0]), "crc does not match flash");
        TQ_CHECK(crc == cal_crc(&ram.t[0]), "flash does not match ram after burn");
        TQ_PASS("burn verified");
    }

    TQ_CASE("a corrupted frame is dropped, not answered");
    setup();
    {
        u8 frame[64];
        u32 n = proto_frame(CMD_IDENTIFY, 0, 0, frame, sizeof(frame));
        frame[n - 1] ^= 0xFFu;                     /* wreck the CRC */
        u32 r = proto_feed(&p, frame, n, out, sizeof(out));
        TQ_CHECK(r == 0, "the ECU answered a corrupted frame");
        TQ_CHECK(p.frames_bad_crc == 1, "bad frame not counted");
        /* and the link still works afterwards */
        TQ_CHECK(send(CMD_IDENTIFY, 0, 0) > 0, "link dead after one bad frame");
        TQ_PASS("corrupted frames dropped");
    }

    TQ_CASE("the link resynchronises after garbage");
    setup();
    {
        u8 junk[19];
        memset(junk, 0x33, sizeof(junk));
        proto_feed(&p, junk, sizeof(junk), out, sizeof(out));
        TQ_CHECK(send(CMD_IDENTIFY, 0, 0) > 0, "never resynced");
        TQ_PASS("resync");
    }

    TQ_CASE("an absurd length field does not hang or overrun");
    setup();
    {
        u8 frame[16] = { PROTO_SYNC0, PROTO_SYNC1, CMD_IDENTIFY, 0xFF, 0xFF,
                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
        proto_feed(&p, frame, sizeof(frame), out, sizeof(out));
        TQ_CHECK(send(CMD_IDENTIFY, 0, 0) > 0, "link dead after a bad length");
        TQ_PASS("bad length survived");
    }

    TQ_CASE("an unknown command is answered, not ignored");
    setup();
    {
        TQ_CHECK(send(0x7F, 0, 0) > 0, "no reply to an unknown command");
        TQ_CHECK(out[5] == ST_BAD_CMD, "status %d", out[5]);
        TQ_PASS("unknown command");
    }

    return tq_report("protocol");
}
