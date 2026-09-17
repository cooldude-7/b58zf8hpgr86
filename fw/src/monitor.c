#include "monitor.h"

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

void tq_monitor_reset(tq_monitor_t *m)
{
    m->limp = MON_OK;
    m->fault = MON_F_NONE;
    m->fault_mask = 0;
    m->permissible = 0.0f;
    m->t_pedal = m->t_tps = m->t_track = m->t_torque = 0.0f;
}

static f32 permissible_torque(f32 pedal_pct, f32 rpm, f32 max_torque)
{
    f32 p = tq_clampf(pedal_pct, 0.0f, 100.0f) / 100.0f;
    f32 idle_allowance = rpm < 1500.0f ? 40.0f : 15.0f;
    return idle_allowance + p * max_torque;
}

static void raise_fault(u8 code, mon_limp_t limp,
                        u8 *out_fault, mon_limp_t *out_limp)
{
    *out_fault = code;
    *out_limp = limp;
}

mon_limp_t tq_monitor_update(tq_monitor_t *m, const mon_inputs_t *in)
{
    u8 fault = MON_F_NONE;
    mon_limp_t limp = MON_OK;

    m->t_pedal = absf(in->pedal_a - in->pedal_b) > MON_PEDAL_DISAGREE_PCT
                 ? m->t_pedal + in->dt : 0.0f;
    m->t_tps = absf(in->tps_a - in->tps_b) > MON_TPS_DISAGREE_PCT
               ? m->t_tps + in->dt : 0.0f;
    m->t_track = absf(in->tps_cmd - in->tps_a) > MON_TPS_TRACKING_PCT
                 ? m->t_track + in->dt : 0.0f;

    /* With a pedal fault the lower of the two tracks is the safe read. */
    f32 pedal = in->pedal_a;
    if (m->t_pedal > MON_DEBOUNCE_S) {
        pedal = in->pedal_a < in->pedal_b ? in->pedal_a : in->pedal_b;
    }
    m->permissible = permissible_torque(pedal, in->rpm, in->max_torque);
    bool over = in->torque > m->permissible + MON_TORQUE_MARGIN_NM;
    m->t_torque = over ? m->t_torque + in->dt : 0.0f;

    if (m->t_pedal > MON_DEBOUNCE_S)
        raise_fault(MON_F_PEDAL_PLAUSIBILITY, MON_REDUCED, &fault, &limp);
    if (m->t_tps > MON_DEBOUNCE_S)
        raise_fault(MON_F_TPS_PLAUSIBILITY, MON_IDLE_ONLY, &fault, &limp);
    if (m->t_track > MON_DEBOUNCE_S)
        raise_fault(MON_F_TPS_TRACKING, MON_IDLE_ONLY, &fault, &limp);
    if (m->t_torque > MON_TORQUE_DEBOUNCE_S)
        raise_fault(MON_F_TORQUE_EXCEEDS_PERMISSIBLE, MON_IDLE_ONLY,
                    &fault, &limp);
    if (in->rpm > in->rev_limit + 500.0f)
        raise_fault(MON_F_OVERSPEED, MON_SHUTDOWN, &fault, &limp);
    if (in->map_kpa > in->overboost_kpa)
        raise_fault(MON_F_OVERBOOST, MON_SHUTDOWN, &fault, &limp);

    if (fault != MON_F_NONE) {
        u16 bit = (u16)(1u << fault);
        if (!(m->fault_mask & bit)) {
            m->fault_mask |= bit;
            if (m->fault == MON_F_NONE) {
                m->fault = fault;      /* root cause, not last symptom */
            }
        }
    }
    /* A limp latches until the key is cycled: a fault that clears its own
     * limp is an engine that keeps retrying a dangerous condition. */
    if (limp > m->limp) {
        m->limp = limp;
    }
    return m->limp;
}

f32 tq_monitor_torque_cap(const tq_monitor_t *m, f32 max_torque)
{
    switch (m->limp) {
    case MON_OK:        return max_torque;
    case MON_REDUCED:   return 0.5f * max_torque;
    case MON_IDLE_ONLY: return 30.0f;
    default:            return 0.0f;
    }
}
