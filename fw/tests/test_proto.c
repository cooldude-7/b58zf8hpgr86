/* Framing and command handling, including the ways a link misbehaves. */
#include <stddef.h>
#include <string.h>

#include "chan.h"
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

    /* ---- live channels ---------------------------------------------- */
    TQ_CASE("the channel list describes itself");
    setup();
    {
        /* Without a signal block the command answers a status rather
         * than a block of zeroes. A gauge reading zero and a gauge
         * reading nothing look identical on screen and are not the
         * same thing. */
        u8 op = CH_OP_VALUES;
        TQ_CHECK(send(CMD_CHANNELS, &op, 1) > 0, "no reply");
        TQ_CHECK(out[5] == ST_NOT_ALLOWED,
                 "answered %d with no signals attached", out[5]);

        static ecu_signals_t sig;
        memset(&sig, 0, sizeof(sig));
        proto_set_signals(&p, &sig);

        op = CH_OP_DESCRIBE;
        u32 n = send(CMD_CHANNELS, &op, 1);
        TQ_CHECK(n > 0, "no reply to describe");
        TQ_CHECK(out[5] == ST_OK, "status %d", out[5]);
        u8 count = out[6];
        TQ_CHECK(count == chan_count(), "described %u of %u channels",
                 count, chan_count());
        u32 hash;
        memcpy(&hash, out + 7, 4);
        TQ_CHECK(hash == chan_hash(), "hash does not match the table");
        TQ_CHECK(hash != 0, "a hash of zero cannot detect anything");
        TQ_CHECK(n == 7u + 4u + (u32)count * CHAN_NAME_LEN + 2u,
                 "describe reply is %u bytes for %u channels", n, count);

        /* Every name arrives NUL terminated inside its field, so the
         * tuner indexes rather than parses, and no two are the same --
         * a duplicate would put two signals on one gauge. */
        for (u8 i = 0; i < count; i++) {
            const u8 *ni = out + 11 + (u32)i * CHAN_NAME_LEN;
            TQ_CHECK(ni[CHAN_NAME_LEN - 1] == 0,
                     "channel %u name fills its field with no terminator", i);
            TQ_CHECK(ni[0] != 0, "channel %u has an empty name", i);
            TQ_CHECK(!strncmp((const char *)ni, chan_at(i)->key, CHAN_NAME_LEN),
                     "channel %u is named %s on the wire and %s in the table",
                     i, (const char *)ni, chan_at(i)->key);
            for (u8 j = (u8)(i + 1); j < count; j++) {
                const u8 *nj = out + 11 + (u32)j * CHAN_NAME_LEN;
                TQ_CHECK(strncmp((const char *)ni, (const char *)nj,
                                 CHAN_NAME_LEN) != 0,
                         "channels %u and %u are both called %s", i, j,
                         (const char *)ni);
            }
            if (tq_fails) break;
        }
        TQ_PASS("describe");
    }

    TQ_CASE("channel values are the signals, in the units the name implies");
    setup();
    {
        static ecu_signals_t sig;
        memset(&sig, 0, sizeof(sig));
        sig.rpm = 3450.0f;
        sig.map_kpa = 158.0f;
        sig.clt_k = 361.15f;             /* 88 C */
        sig.iat_k = 304.15f;             /* 31 C */
        sig.pw_us = 4250u;               /* 4.25 ms */
        sig.state = ECU_RUNNING;
        sig.pump_on = true;
        sig.fan_on = false;
        sig.n_pulses = 2;
        proto_set_signals(&p, &sig);

        u8 op = CH_OP_VALUES;
        u32 n = send(CMD_CHANNELS, &op, 1);
        TQ_CHECK(out[5] == ST_OK, "status %d", out[5]);
        u8 count = out[6];
        TQ_CHECK(n == 7u + 4u + (u32)count * 4u + 2u,
                 "values reply is %u bytes for %u channels", n, count);

        for (u8 i = 0; i < count; i++) {
            f32 v;
            memcpy(&v, out + 11 + (u32)i * 4u, 4);
            const char *k = chan_at(i)->key;
            TQ_NEAR(v, chan_value(&sig, i), 1e-6,
                    "channel %s went down the wire wrong", k);
            /* Spot-check the conversions themselves. A gauge in the
             * wrong unit is the kind of thing that reads plausibly
             * for a whole session. */
            if (!strcmp(k, "rpm"))   TQ_NEAR(v, 3450.0f, 1e-3, "rpm");
            if (!strcmp(k, "map"))   TQ_NEAR(v, 158.0f, 1e-3, "map");
            if (!strcmp(k, "boost")) TQ_NEAR(v, 8.22f, 0.02f,
                                             "158 kPa absolute is 8.2 psi of "
                                             "boost, got %.2f", (double)v);
            if (!strcmp(k, "clt"))   TQ_NEAR(v, 88.0f, 0.05f, "coolant in C");
            if (!strcmp(k, "iat"))   TQ_NEAR(v, 31.0f, 0.05f, "intake in C");
            if (!strcmp(k, "pw_ms")) TQ_NEAR(v, 4.25f, 1e-3, "pulse width in ms");
            if (!strcmp(k, "state")) TQ_NEAR(v, (f32)ECU_RUNNING, 1e-6, "state");
            if (!strcmp(k, "pump"))  TQ_NEAR(v, 1.0f, 1e-6, "a bool reads 1");
            if (!strcmp(k, "fan"))   TQ_NEAR(v, 0.0f, 1e-6, "a bool reads 0");
            if (!strcmp(k, "inj_pulses")) TQ_NEAR(v, 2.0f, 1e-6, "pulse count");
            if (tq_fails) break;
        }
        TQ_PASS("values");
    }

    TQ_CASE("every channel reads its own field");
    setup();
    {
        /* The failure this catches is a mistyped offsetof: the channel
         * still reports a number, the number is plausible, and it
         * belongs to a different signal. Walk the table, poke a marker
         * into each field through its own descriptor, and read it back
         * through the public path. */
        static ecu_signals_t sig;
        for (u8 i = 0; i < chan_count(); i++) {
            const chan_desc_t *d = chan_at(i);
            u32 size = d->type == CH_F32 || d->type == CH_I32
                    || d->type == CH_U32 ? 4u
                     : d->type == CH_U16 ? 2u : 1u;
            TQ_CHECK((u32)d->off + size <= sizeof(sig),
                     "channel %s points %u bytes past the signal block",
                     d->key, (u32)d->off + size - (u32)sizeof(sig));
            if (tq_fails) break;

            memset(&sig, 0, sizeof(sig));
            u8 *field = (u8 *)&sig + d->off;
            f32 raw = 0.0f;
            switch (d->type) {
            case CH_F32:  { f32 v = 12.5f; memcpy(field, &v, 4); raw = v; break; }
            case CH_I32:  { int v = 3; memcpy(field, &v, 4); raw = 3.0f; break; }
            case CH_U32:  { u32 v = 7u; memcpy(field, &v, 4); raw = 7.0f; break; }
            case CH_U16:  { u16 v = 9u; memcpy(field, &v, 2); raw = 9.0f; break; }
            case CH_U8:   { u8 v = 5u; memcpy(field, &v, 1); raw = 5.0f; break; }
            case CH_BOOL: { bool v = true; memcpy(field, &v, 1); raw = 1.0f; break; }
            default: TQ_CHECK(0, "channel %s has type %u", d->key, d->type);
            }
            TQ_NEAR(chan_value(&sig, i), raw * d->scale + d->bias, 1e-4,
                    "channel %s does not read the field it points at", d->key);
            if (tq_fails) break;
        }
        TQ_PASS("offsets");
    }

    TQ_CASE("a malformed channel request is refused");
    setup();
    {
        static ecu_signals_t sig;
        memset(&sig, 0, sizeof(sig));
        proto_set_signals(&p, &sig);

        TQ_CHECK(send(CMD_CHANNELS, 0, 0) > 0, "no reply to an empty payload");
        TQ_CHECK(out[5] == ST_BAD_LEN, "empty payload answered %d", out[5]);

        u8 two[2] = { CH_OP_VALUES, CH_OP_VALUES };
        TQ_CHECK(send(CMD_CHANNELS, two, 2) > 0, "no reply to a long payload");
        TQ_CHECK(out[5] == ST_BAD_LEN, "long payload answered %d", out[5]);

        u8 op = 0x7E;
        TQ_CHECK(send(CMD_CHANNELS, &op, 1) > 0, "no reply to a bad sub-op");
        TQ_CHECK(out[5] == ST_BAD_VALUE, "bad sub-op answered %d", out[5]);

        /* And the link still works afterwards. */
        op = CH_OP_VALUES;
        TQ_CHECK(send(CMD_CHANNELS, &op, 1) > 0, "link dead after a refusal");
        TQ_CHECK(out[5] == ST_OK, "status %d", out[5]);
        TQ_PASS("malformed requests");
    }

    TQ_CASE("a channel reply survives being dribbled in");
    setup();
    {
        static ecu_signals_t sig;
        memset(&sig, 0, sizeof(sig));
        sig.rpm = 1234.0f;
        proto_set_signals(&p, &sig);
        u8 op = CH_OP_DESCRIBE;
        TQ_CHECK(send_dribbled(CMD_CHANNELS, &op, 1) > 0, "no reply");
        TQ_CHECK(out[5] == ST_OK, "status %d", out[5]);
        TQ_PASS("dribbled");
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
