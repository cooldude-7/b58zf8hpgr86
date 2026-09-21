#include "chan.h"

#include <stddef.h>
#include <string.h>

#include "cal.h"                 /* tq_crc32 */

#define SIG(field) (u16)offsetof(ecu_signals_t, field)

/* kPa to psi, and absolute to gauge: what a boost gauge in a car shows. */
#define KPA_PSI 0.1450377f
#define ATM_PSI (-14.6959f)
#define K_TO_C (-273.15f)

static const chan_desc_t g_chan[] = {
    /* air path */
    { "rpm",           SIG(rpm),             CH_F32,  1.0f,      0.0f },
    { "map",           SIG(map_kpa),         CH_F32,  1.0f,      0.0f },
    { "boost",         SIG(map_kpa),         CH_F32,  KPA_PSI,   ATM_PSI },
    { "map_target",    SIG(map_target_kpa),  CH_F32,  1.0f,      0.0f },
    { "tps",           SIG(tps_a),           CH_F32,  1.0f,      0.0f },
    { "tps_a",         SIG(tps_a),           CH_F32,  1.0f,      0.0f },
    { "tps_b",         SIG(tps_b),           CH_F32,  1.0f,      0.0f },
    { "tps_cmd",       SIG(tps_cmd),         CH_F32,  1.0f,      0.0f },
    { "pedal_a",       SIG(pedal_a),         CH_F32,  1.0f,      0.0f },
    { "pedal_b",       SIG(pedal_b),         CH_F32,  1.0f,      0.0f },
    { "wastegate",     SIG(wastegate_pct),   CH_F32,  1.0f,      0.0f },
    { "air",           SIG(air_g),           CH_F32,  1.0f,      0.0f },
    { "ve",            SIG(ve),              CH_F32,  1.0f,      0.0f },

    /* measured */
    { "clt",           SIG(clt_k),           CH_F32,  1.0f,      K_TO_C },
    { "iat",           SIG(iat_k),           CH_F32,  1.0f,      K_TO_C },
    { "batt",          SIG(battery_v),       CH_F32,  1.0f,      0.0f },
    { "oil_kpa",       SIG(oil_kpa),         CH_F32,  1.0f,      0.0f },

    /* torque */
    { "torque",        SIG(torque_estimate), CH_F32,  1.0f,      0.0f },
    { "torque_req",    SIG(torque_request),  CH_F32,  1.0f,      0.0f },
    { "authority",     SIG(torque_authority),CH_F32,  1.0f,      0.0f },
    { "idle_target",   SIG(idle_target_rpm), CH_F32,  1.0f,      0.0f },

    /* spark */
    { "spark",         SIG(spark_deg),       CH_F32,  1.0f,      0.0f },
    { "mbt",           SIG(mbt_deg),         CH_F32,  1.0f,      0.0f },
    { "knock",         SIG(knock_limit_deg), CH_F32,  1.0f,      0.0f },

    /* fuel */
    { "lambda",        SIG(lambda_meas),     CH_F32,  1.0f,      0.0f },
    { "lambda_target", SIG(lambda_target),   CH_F32,  1.0f,      0.0f },
    { "lambda_trim",   SIG(lambda_trim),     CH_F32,  1.0f,      0.0f },
    { "enrich",        SIG(enrich_mult),     CH_F32,  1.0f,      0.0f },
    { "pw_ms",         SIG(pw_us),           CH_U32,  0.001f,    0.0f },
    { "rail_kpa",      SIG(rail_kpa),        CH_F32,  1.0f,      0.0f },
    { "rail_target",   SIG(rail_target_kpa), CH_F32,  1.0f,      0.0f },
    { "soi",           SIG(soi_deg),         CH_F32,  1.0f,      0.0f },
    { "inj_split",     SIG(split_first),     CH_F32,  1.0f,      0.0f },
    { "inj_pulses",    SIG(n_pulses),        CH_U8,   1.0f,      0.0f },
    { "msv_events",    SIG(msv_events),      CH_U32,  1.0f,      0.0f },

    /* cams. Sent whether or not the measurement is valid, with the
     * validity beside it -- a phase reading that has gone stale looks
     * exactly like a phaser sitting still, and the difference matters
     * to whoever is watching. */
    { "cam_adv_in",    SIG(cam_adv[0]),      CH_F32,  1.0f,      0.0f },
    { "cam_adv_ex",    SIG(cam_adv[1]),      CH_F32,  1.0f,      0.0f },
    { "cam_valid_in",  SIG(cam_adv_valid[0]),CH_BOOL, 1.0f,      0.0f },
    { "cam_valid_ex",  SIG(cam_adv_valid[1]),CH_BOOL, 1.0f,      0.0f },

    /* state and faults */
    { "state",         SIG(state),           CH_I32,  1.0f,      0.0f },
    { "sensor_faults", SIG(sensor_faults),   CH_U16,  1.0f,      0.0f },
    { "decel_cut",     SIG(decel_cut),       CH_BOOL, 1.0f,      0.0f },
    { "lambda_closed", SIG(lambda_closed),   CH_BOOL, 1.0f,      0.0f },
    { "boost_low",     SIG(boost_low),       CH_BOOL, 1.0f,      0.0f },
    { "pump",          SIG(pump_on),         CH_BOOL, 1.0f,      0.0f },
    { "fan",           SIG(fan_on),          CH_BOOL, 1.0f,      0.0f },
};

#define CHAN_N ((u8)(sizeof(g_chan) / sizeof(g_chan[0])))

u8 chan_count(void)
{
    return CHAN_N;
}

const chan_desc_t *chan_at(u8 i)
{
    return i < CHAN_N ? &g_chan[i] : 0;
}

f32 chan_value(const ecu_signals_t *s, u8 i)
{
    if (i >= CHAN_N || !s) {
        return 0.0f;
    }
    const chan_desc_t *d = &g_chan[i];
    const u8 *p = (const u8 *)s + d->off;
    f32 raw = 0.0f;

    /* memcpy rather than a cast: the fields are aligned, but a
     * descriptor with a mistyped offset would be undefined behaviour
     * rather than a wrong number, and a wrong number is easier to
     * find. */
    switch (d->type) {
    case CH_F32: { f32 v; memcpy(&v, p, sizeof v); raw = v; break; }
    case CH_I32: { int v; memcpy(&v, p, sizeof v); raw = (f32)v; break; }
    case CH_U32: { u32 v; memcpy(&v, p, sizeof v); raw = (f32)v; break; }
    case CH_U16: { u16 v; memcpy(&v, p, sizeof v); raw = (f32)v; break; }
    case CH_U8:  { u8  v; memcpy(&v, p, sizeof v); raw = (f32)v; break; }
    case CH_BOOL:{ bool v; memcpy(&v, p, sizeof v); raw = v ? 1.0f : 0.0f; break; }
    default: return 0.0f;
    }
    return raw * d->scale + d->bias;
}

u32 chan_hash(void)
{
    u32 h = 0;
    for (u8 i = 0; i < CHAN_N; i++) {
        h = tq_crc32(h, g_chan[i].key, (u32)strlen(g_chan[i].key));
    }
    return h;
}
