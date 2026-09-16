"""Shift coordinator -- YOUR EXERCISE.

This is the "brain" piece: the thing that decides what spark and what air
request to command, moment by moment, while the transmission executes a
shift.

The physics lives in tqmodel/model.py and is already written. Nothing here
computes torque from first principles -- this file only *decides things*.

WHAT TO DO
    Find the four TODO blocks in ShiftCoordinator.update() and fill them
    in. Everything else is done for you.

CHECK YOUR WORK
    python tools\\shift\\simulate.py      -> plots what your code does
    python tools\\shift\\test_shift.py    -> pass/fail on six behaviours

Right now the TODOs return placeholder values, so the simulation runs but
the plot is wrong. Your job is to make it right.
"""
from dataclasses import dataclass
from enum import Enum

import numpy as np

from tqmodel.model import spark_efficiency


class ShiftState(Enum):
    """Where we are in the shift.

    IDLE       nothing happening, pass the driver's request straight through
    CUTTING    ramping torque DOWN to the target (fast, ~50 ms)
    HOLDING    torque held at the target while the clutch does its work
    RESTORING  ramping torque back UP to the driver's request (slow, ~150 ms)
    """
    IDLE = "idle"
    CUTTING = "cutting"
    HOLDING = "holding"
    RESTORING = "restoring"


@dataclass
class ShiftRequest:
    """What the transmission asks for when it starts a shift."""
    target_torque_nm: float      # hold torque down to this
    ramp_in_ms: float = 50.0     # how fast to pull it down
    hold_ms: float = 250.0       # the inertia phase
    ramp_out_ms: float = 150.0   # how slowly to give it back


@dataclass
class Command:
    """What the coordinator outputs every tick."""
    spark_deg: float             # commanded spark, degrees BTDC
    air_request_nm: float        # torque the AIR path should size for
    torque_target_nm: float      # what we are actually aiming to produce
    state: ShiftState


# ---------------------------------------------------------------------------
# Given to you: the algebra for going from a torque ratio back to a spark
# angle. This inverts spark_efficiency() from tqmodel/model.py, which is
#     eff = 1 - A*d - B*d^2
# so finding d for a desired eff is just the quadratic formula. Fiddly
# algebra, not architecture -- so it is written for you.
# ---------------------------------------------------------------------------
_A, _B = 6.667e-3, 3.333e-4


def retard_for_efficiency(eff_wanted: float) -> float:
    """Degrees of retard from MBT that produce this torque fraction.

    eff_wanted = 1.0 -> 0 degrees (sit at MBT)
    eff_wanted = 0.5 -> about 30 degrees
    """
    eff = float(np.clip(eff_wanted, 0.05, 1.0))
    disc = _A ** 2 + 4.0 * _B * (1.0 - eff)
    return float(np.clip((-_A + np.sqrt(disc)) / (2.0 * _B), 0.0, 35.0))


class ShiftCoordinator:
    """Decides spark and air commands during a shift.

    Usage each tick:
        cmd = coord.update(dt, driver_torque_nm, mbt_deg)
    """

    def __init__(self, chase_air_bug: bool = False):
        self.state = ShiftState.IDLE
        self.t_in_state = 0.0          # seconds elapsed in current state
        self.req: ShiftRequest | None = None
        self.torque_at_cut_start = 0.0  # torque when the shift began
        self.frozen_air_nm = 0.0        # air request held during the shift

        # Set True to deliberately reproduce the air-chase bug and watch
        # the cut get diluted. See docs/torque-model.md.
        self.chase_air_bug = chase_air_bug

    def request_shift(self, req: ShiftRequest, current_torque_nm: float):
        """Transmission calls this once, at the start of a shift."""
        self.req = req
        self.state = ShiftState.CUTTING
        self.t_in_state = 0.0
        self.torque_at_cut_start = current_torque_nm
        self.frozen_air_nm = current_torque_nm

    # -----------------------------------------------------------------
    def update(self, dt: float, driver_torque_nm: float,
               mbt_deg: float) -> Command:
        """Run one control tick.

        dt                seconds since last tick
        driver_torque_nm  what the pedal is asking for right now
        mbt_deg           MBT spark at the current operating point

        Returns a Command.
        """
        self.t_in_state += dt

        # ==== TODO 1: advance the state machine ==========================
        # Move to the next state when the current one has run its course.
        #   CUTTING   -> HOLDING    after req.ramp_in_ms
        #   HOLDING   -> RESTORING  after req.hold_ms
        #   RESTORING -> IDLE       after req.ramp_out_ms
        # Remember to reset self.t_in_state to 0.0 on every transition.
        # Note the times in ShiftRequest are in MILLISECONDS and dt is in
        # SECONDS.
        #
        # (placeholder -- delete this line once you have written it)
        pass

        # ==== TODO 2: work out the torque target for right now ===========
        # IDLE       -> just the driver's request
        # CUTTING    -> ramp linearly from torque_at_cut_start down to
        #               req.target_torque_nm over ramp_in_ms
        # HOLDING    -> sit at req.target_torque_nm
        # RESTORING  -> ramp linearly from req.target_torque_nm back up to
        #               driver_torque_nm over ramp_out_ms
        #
        # Hint: a linear ramp from a to b, fraction f of the way through,
        # is    a + (b - a) * f
        # and   f = self.t_in_state / (duration_ms / 1000.0)
        # clamped to the range 0..1 with np.clip.
        #
        torque_target = driver_torque_nm        # placeholder -- replace

        # ==== TODO 3: turn that torque target into a spark angle =========
        # The ratio you want is torque_target / torque_at_cut_start (when
        # a shift is running) -- that is the fraction of the pre-shift
        # torque you are trying to produce, and the air has not changed,
        # so spark has to do all of it.
        #
        # When IDLE, just sit at MBT.
        #
        # Use retard_for_efficiency() above, then:
        #     spark = mbt_deg - retard
        #
        spark = mbt_deg                          # placeholder -- replace

        # ==== TODO 4: decide the AIR request -- the important one ========
        # This is the rule from docs/torque-model.md.
        #
        # While a shift is running (any state except IDLE), the air path
        # must HOLD -- keep asking for self.frozen_air_nm. It must NOT be
        # told about the cut, or it will open the throttle to compensate
        # and dilute the whole thing.
        #
        # When IDLE, the air request is simply the driver's request.
        #
        # If self.chase_air_bug is True, deliberately do the WRONG thing:
        # an air path that does not know the cut was intentional sees the
        # retard as lost efficiency and asks for MORE air to make up for
        # it --
        #     air_request = driver_torque_nm / efficiency_right_now
        # With a 60% cut that demands nearly 3x the air. Use
        # spark_efficiency() from tqmodel.model to get the efficiency at
        # your commanded spark.
        #
        air_request = driver_torque_nm           # placeholder -- replace

        return Command(spark_deg=spark,
                       air_request_nm=air_request,
                       torque_target_nm=torque_target,
                       state=self.state)
