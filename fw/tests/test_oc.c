/* Output-compare scheduling logic.
 *
 * Each of these is a way a coil or an injector misbehaves on a real
 * engine, not an abstract state-machine property.
 */
#include "oc_core.h"
#include "tq_test.h"

int main(void)
{
    TQ_CASE("a request already in the past is refused, not fired late");
    {
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        TQ_CHECK(!oc_request(&s, 1000u, 3000u, 2000u, &a),
                 "accepted a rising edge that had already gone");
        TQ_CHECK(a == OC_ACT_NONE, "asked the hardware to do something anyway");
        TQ_CHECK(s.st == OC_IDLE, "changed state on a refused request");
    }

    TQ_CASE("re-arming before the rising edge replaces it outright");
    {
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        oc_request(&s, 5000u, 8000u, 1000u, &a);
        TQ_CHECK(oc_request(&s, 6000u, 9000u, 1000u, &a), "refused a revision");
        TQ_CHECK(a == OC_ACT_ARM_RISE, "did not re-arm the rising edge");
        TQ_CHECK(s.on_us == 6000u && s.off_us == 9000u, "kept the old edges");
        TQ_PASS("a spark can be revised until it starts");
    }

    TQ_CASE("re-arming a channel already high moves ONLY the falling edge");
    {
        /* Retracting a dwell that has started is a misfire, and on an
         * injector it is a cylinder that got less fuel than the model
         * thinks it did. */
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        oc_request(&s, 5000u, 8000u, 1000u, &a);
        oc_on_match(&s);                        /* rising edge fires */
        TQ_CHECK(s.st == OC_HIGH, "not high after the rising edge");
        TQ_CHECK(oc_request(&s, 6000u, 9000u, 5500u, &a), "refused");
        TQ_CHECK(a == OC_ACT_ARM_FALL, "tried to re-arm a started rising edge");
        TQ_CHECK(s.on_us == 5000u, "moved the rising edge after it fired");
        TQ_CHECK(s.off_us == 9000u, "did not move the falling edge");
        TQ_PASS("a started dwell cannot be retracted, only extended");
    }

    TQ_CASE("cancelling a channel that is high drives it low");
    {
        /* sched.c cancels an injector mid-pulse on purpose: fuel is the
         * fast cut. Merely disarming leaves the pin where it is, and
         * where it is is on. */
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        oc_request(&s, 5000u, 8000u, 1000u, &a);
        oc_on_match(&s);
        TQ_CHECK(oc_cancel(&s) == OC_ACT_FORCE_LOW,
                 "left an injector open after a cancel");
        TQ_CHECK(!oc_is_active(&s), "still reports active");
        TQ_PASS("fuel is retractable mid-pulse");
    }

    TQ_CASE("cancelling an armed channel does not need to force anything");
    {
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        oc_request(&s, 5000u, 8000u, 1000u, &a);
        TQ_CHECK(oc_cancel(&s) == OC_ACT_NONE, "forced a pin that was already low");
    }

    TQ_CASE("a lost falling edge is rescued, and the channel works again");
    {
        /* THE one that ends a cylinder's life. If a compare interrupt is
         * missed while a channel is high, nothing else ever moves it:
         * the coil charges indefinitely, and because the slot never
         * returns to idle, that injector is never scheduled again. */
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        oc_request(&s, 5000u, 8000u, 1000u, &a);
        oc_on_match(&s);                         /* rising edge */
        /* ...and the falling edge interrupt never arrives. */
        TQ_CHECK(oc_sweep(&s, 8500u, 2000u) == OC_ACT_NONE,
                 "rescued too early, inside the legitimate margin");
        TQ_CHECK(oc_sweep(&s, 11000u, 2000u) == OC_ACT_FORCE_LOW,
                 "never rescued a channel stuck high");
        TQ_CHECK(s.st == OC_IDLE, "left the slot unusable");
        TQ_CHECK(s.lost_edges == 1u, "did not count the lost edge");

        /* And the proof that matters: it can be scheduled again. */
        TQ_CHECK(oc_request(&s, 20000u, 23000u, 15000u, &a),
                 "the cylinder never got another pulse");
        TQ_PASS("a missed interrupt costs one event, not the cylinder");
    }

    TQ_CASE("a multi-pulse sequence walks through in order");
    {
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        hal_pulse_t p[3] = {{5000u, 6000u}, {7000u, 8000u}, {9000u, 10000u}};
        TQ_CHECK(oc_request_pulses(&s, p, 3, 1000u, &a), "refused a valid set");
        TQ_CHECK(a == OC_ACT_ARM_RISE, "did not arm the first pulse");
        for (int i = 0; i < 3; i++) {
            TQ_CHECK(oc_on_match(&s) == OC_ACT_ARM_FALL, "pulse %d rise", i);
            oc_action_t nxt = oc_on_match(&s);
            if (i < 2) {
                TQ_CHECK(nxt == OC_ACT_ARM_RISE, "pulse %d did not chain", i);
            } else {
                TQ_CHECK(nxt == OC_ACT_NONE, "kept going past the last pulse");
                TQ_CHECK(s.st == OC_IDLE, "did not finish idle");
            }
        }
        TQ_PASS("split injection walks its whole sequence");
    }

    TQ_CASE("an overlapping or out-of-order sequence is refused whole");
    {
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        hal_pulse_t good[2] = {{5000u, 6000u}, {7000u, 8000u}};
        oc_request_pulses(&s, good, 2, 1000u, &a);
        hal_pulse_t overlap[2] = {{5000u, 7500u}, {7000u, 9000u}};
        TQ_CHECK(!oc_request_pulses(&s, overlap, 2, 1000u, &a),
                 "accepted overlapping pulses");
        TQ_CHECK(s.off_us == 6000u,
                 "half-applied a rejected pattern (off=%u)", s.off_us);
        TQ_PASS("a rejected pattern leaves the old one intact");
    }

    TQ_CASE("everything survives the 71-minute counter wrap");
    {
        /* The microsecond counter wraps every ~71 minutes. A direct <
         * comparison fails exactly once per wrap, which is the kind of
         * fault that only ever shows up on a long drive. */
        oc_slot_t s; oc_reset(&s);
        oc_action_t a;
        tq_time_t now = 0xFFFFF000u;             /* just before the wrap */
        tq_time_t on  = now + 0x800u;
        tq_time_t off = now + 0x1800u;           /* lands past zero */
        TQ_CHECK(oc_request(&s, on, off, now, &a), "refused a valid edge at the wrap");
        TQ_CHECK(a == OC_ACT_ARM_RISE, "did not arm across the wrap");
        oc_on_match(&s);
        TQ_CHECK(oc_sweep(&s, off + 500u, 2000u) == OC_ACT_NONE,
                 "rescued a healthy channel because the counter wrapped");
        TQ_CHECK(oc_sweep(&s, off + 4000u, 2000u) == OC_ACT_FORCE_LOW,
                 "failed to rescue across the wrap");
        TQ_PASS("signed differences, not less-than");
    }

    return tq_report("oc_core");
}
