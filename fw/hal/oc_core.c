#include "oc_core.h"

void oc_reset(oc_slot_t *s)
{
    for (u32 i = 0; i < sizeof(*s); i++) {
        ((u8 *)s)[i] = 0;
    }
    s->st = OC_IDLE;
}

bool oc_is_active(const oc_slot_t *s)
{
    return s->st == OC_HIGH;
}

bool oc_request(oc_slot_t *s, tq_time_t on_us, tq_time_t off_us,
                tq_time_t now_us, oc_action_t *act)
{
    *act = OC_ACT_NONE;

    if (s->st == OC_HIGH) {
        /* Already charging or already injecting. The rising edge cannot
         * be taken back, so honour only the new falling edge -- and only
         * if it is still ahead of us. */
        if (!tq_after(off_us, now_us)) {
            return false;
        }
        s->off_us = off_us;
        s->n_q = 0;
        s->head = 0;
        *act = OC_ACT_ARM_FALL;
        return true;
    }

    /* Signed comparison throughout: the microsecond counter wraps every
     * 71 minutes and a direct < fails once per wrap. */
    if (!tq_after(on_us, now_us) || !tq_after(off_us, on_us)) {
        return false;
    }
    s->on_us = on_us;
    s->off_us = off_us;
    s->n_q = 0;
    s->head = 0;
    s->st = OC_ARMED;
    *act = OC_ACT_ARM_RISE;
    return true;
}

bool oc_request_pulses(oc_slot_t *s, const hal_pulse_t *p, u8 n,
                       tq_time_t now_us, oc_action_t *act)
{
    *act = OC_ACT_NONE;
    if (n == 0u || n > HAL_MAX_PULSES) {
        return false;
    }
    /* Validate the whole sequence before touching anything. */
    for (u8 i = 0; i < n; i++) {
        if (!tq_after(p[i].off_us, p[i].on_us)) {
            return false;
        }
        if (i > 0u && !tq_after(p[i].on_us, p[i - 1].off_us)) {
            return false;            /* out of order or overlapping */
        }
    }
    if (s->st == OC_HIGH) {
        /* Mid-pulse: keep the edge that has started, queue the rest. */
        if (!tq_after(p[0].off_us, now_us)) {
            return false;
        }
        s->off_us = p[0].off_us;
        *act = OC_ACT_ARM_FALL;
    } else {
        if (!tq_after(p[0].on_us, now_us)) {
            return false;
        }
        s->on_us = p[0].on_us;
        s->off_us = p[0].off_us;
        s->st = OC_ARMED;
        *act = OC_ACT_ARM_RISE;
    }
    s->n_q = (u8)(n - 1u);
    s->head = 0;
    for (u8 i = 1; i < n; i++) {
        s->q[i - 1u] = p[i];
    }
    return true;
}

oc_action_t oc_on_match(oc_slot_t *s)
{
    switch (s->st) {
    case OC_ARMED:
        /* The rising edge happened. Load the falling edge now, while
         * there is a whole pulse width in which to do it. */
        s->st = OC_HIGH;
        return OC_ACT_ARM_FALL;

    case OC_HIGH:
        /* The falling edge happened. Another pulse waiting? */
        if (s->head < s->n_q) {
            hal_pulse_t nx = s->q[s->head++];
            s->on_us = nx.on_us;
            s->off_us = nx.off_us;
            s->st = OC_ARMED;
            return OC_ACT_ARM_RISE;
        }
        s->st = OC_IDLE;
        s->n_q = 0;
        s->head = 0;
        return OC_ACT_NONE;

    default:
        return OC_ACT_NONE;
    }
}

oc_action_t oc_sweep(oc_slot_t *s, tq_time_t now_us, u32 margin_us)
{
    /* The only state worth rescuing is a channel left high. An armed
     * channel whose rising edge was missed simply never fires, which is
     * a missed event rather than a stuck output. */
    if (s->st != OC_HIGH) {
        return OC_ACT_NONE;
    }
    if (tq_after(now_us, s->off_us + margin_us)) {
        s->lost_edges++;
        s->st = OC_IDLE;
        s->n_q = 0;
        s->head = 0;
        return OC_ACT_FORCE_LOW;
    }
    return OC_ACT_NONE;
}

oc_action_t oc_cancel(oc_slot_t *s)
{
    bool was_high = (s->st == OC_HIGH);
    s->st = OC_IDLE;
    s->n_q = 0;
    s->head = 0;
    /* A channel that is high must be driven low, not merely disarmed:
     * disarming leaves the pin where it is, and where it is is on. */
    return was_high ? OC_ACT_FORCE_LOW : OC_ACT_NONE;
}
