/* Output-compare scheduling, as logic rather than as register writes.
 *
 * This is the part of the STM32H7 HAL that decides WHAT a compare unit
 * should be told; hal_stm32h7.c is the part that writes it. They are
 * separated so this half can be executed and tested on a PC, because it
 * is the half that decides whether a coil stops charging and whether an
 * injector closes, and none of that is testable through a register poke.
 *
 * The rules it enforces come from the contract in hal.h:
 *   - A request whose rising edge is already in the past is refused,
 *     rather than fired late into the wrong part of the cycle.
 *   - Re-arming a channel whose rising edge has NOT yet fired replaces
 *     it outright.
 *   - Re-arming a channel that is already high moves only the falling
 *     edge. Retracting a dwell that has started is a misfire.
 *   - Cancelling a channel that is high drops it immediately: fuel is
 *     the fast cut and must be retractable mid-pulse.
 *
 * And one rule that is not in hal.h because it is about hardware going
 * wrong rather than about what to ask of it: a channel that is high and
 * is past its falling edge by a clear margin is dropped by the periodic
 * sweep. A lost compare interrupt would otherwise leave a coil charging
 * or an injector open indefinitely, and on an injector it also means
 * that cylinder never gets another pulse, because a channel stuck high
 * never returns to idle.
 */
#ifndef TQ_OC_CORE_H
#define TQ_OC_CORE_H

#include "hal.h"
#include "tq_types.h"

typedef enum {
    OC_IDLE = 0,
    OC_ARMED,        /* waiting for the rising edge */
    OC_HIGH          /* output is on; waiting for the falling edge */
} oc_state_t;

/* What the caller must do to the hardware as a result. */
typedef enum {
    OC_ACT_NONE = 0,
    OC_ACT_ARM_RISE,     /* compare := on_us, drive high on match */
    OC_ACT_ARM_FALL,     /* compare := off_us, drive low on match */
    OC_ACT_FORCE_LOW     /* drive low now, without waiting for a match */
} oc_action_t;

typedef struct {
    oc_state_t st;
    tq_time_t on_us;
    tq_time_t off_us;
    /* Pulses queued behind the one in flight, for multi-pulse injection.
     * They are handed over as each falling edge completes. */
    hal_pulse_t q[HAL_MAX_PULSES];
    u8 n_q;
    u8 head;
    u32 lost_edges;      /* times the sweep had to rescue a stuck channel */
} oc_slot_t;

void oc_reset(oc_slot_t *s);
bool oc_is_active(const oc_slot_t *s);

/* A single on/off request. Returns false, changing nothing, if it is
 * already in the past. */
bool oc_request(oc_slot_t *s, tq_time_t on_us, tq_time_t off_us,
                tq_time_t now_us, oc_action_t *act);

/* A sequence. Must be in time order and non-overlapping; returns false
 * and keeps the previous set otherwise, because a half-applied injection
 * pattern is worse than an old one. */
bool oc_request_pulses(oc_slot_t *s, const hal_pulse_t *p, u8 n,
                       tq_time_t now_us, oc_action_t *act);

/* The compare unit fired. */
oc_action_t oc_on_match(oc_slot_t *s);

/* Periodic liveness check, from a timer task. `margin_us` is how far past
 * a falling edge a channel may legitimately still be high before this
 * concludes the interrupt was lost. */
oc_action_t oc_sweep(oc_slot_t *s, tq_time_t now_us, u32 margin_us);

oc_action_t oc_cancel(oc_slot_t *s);

#endif /* TQ_OC_CORE_H */
