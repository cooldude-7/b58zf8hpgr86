"""Shift coordinator -- YOUR EXERCISE.

Plain Python only: functions, dictionaries, if/else, and arithmetic.
No classes, no dataclasses, no enums.

WHAT THIS FILE IS
    The "brain". The physics (how much torque you get) already exists in
    tools/tqmodel/. This file only DECIDES THINGS: what spark angle to
    command, and how much air to ask for, at each moment during a shift.

WHAT TO DO
    Fill in the four TODO blocks in update(). About 25 lines total.

CHECK YOUR WORK
    python tools\\shift\\test_shift.py     six pass/fail checks
    python tools\\shift\\simulate.py       plots what your code did
"""

# How long each part of the shift lasts, in milliseconds.
RAMP_IN_MS = 50.0      # pulling torque down -- fast
HOLD_MS = 250.0        # the inertia phase -- clutch doing its work
RAMP_OUT_MS = 150.0    # giving torque back -- slow and gentle


def new_controller():
    """Create the controller's memory.

    Just a dictionary. Everything the controller needs to remember between
    one tick and the next lives in here.
    """
    return {
        "phase": "idle",          # "idle", "cutting", "holding", "restoring"
        "time_in_phase": 0.0,     # seconds spent in the current phase
        "target_torque": 0.0,     # what the transmission asked us to cut to
        "torque_at_start": 0.0,   # torque just before the shift began
        "frozen_air": 0.0,        # the air request we hold during the shift
        "chase_air_bug": False,   # set True to reproduce the classic bug
    }


def start_shift(c, target_torque, current_torque):
    """The transmission calls this once, when a shift begins.

    c               the controller dictionary
    target_torque   cut down to this many Nm
    current_torque  what we are making right now
    """
    c["phase"] = "cutting"
    c["time_in_phase"] = 0.0
    c["target_torque"] = target_torque
    c["torque_at_start"] = current_torque
    c["frozen_air"] = current_torque


def retard_for_fraction(fraction):
    """How many degrees to retard to get this fraction of full torque.

    Given to you -- this is just algebra, not architecture.
        fraction 1.0  ->  0 degrees  (sit at MBT, full torque)
        fraction 0.9  -> 10 degrees
        fraction 0.5  -> 30 degrees
    """
    if fraction > 1.0:
        fraction = 1.0
    if fraction < 0.05:
        fraction = 0.05
    a = 0.006667
    b = 0.0003333
    disc = a * a + 4.0 * b * (1.0 - fraction)
    degrees = (-a + disc ** 0.5) / (2.0 * b)
    if degrees > 35.0:
        degrees = 35.0
    return degrees


def fraction_for_retard(degrees):
    """The opposite: how much torque you get at this much retard.

    Also given to you.
    """
    if degrees < 0.0:
        degrees = 0.0
    f = 1.0 - 0.006667 * degrees - 0.0003333 * degrees * degrees
    if f < 0.0:
        f = 0.0
    return f


def ramp(start_value, end_value, fraction_done):
    """Blend from start_value to end_value.

    fraction_done 0.0 -> start_value
    fraction_done 0.5 -> halfway
    fraction_done 1.0 -> end_value
    """
    if fraction_done < 0.0:
        fraction_done = 0.0
    if fraction_done > 1.0:
        fraction_done = 1.0
    return start_value + (end_value - start_value) * fraction_done


def update(c, dt, driver_torque, mbt):
    """Run one control tick. Called every millisecond.

    c              the controller dictionary (see new_controller)
    dt             seconds since the last tick (0.001)
    driver_torque  what the pedal is asking for, in Nm
    mbt            MBT spark right now, in degrees BTDC

    Returns three numbers:
        spark          the spark angle to command, degrees BTDC
        air_request    how much torque the AIR path should size itself for
        torque_target  what we are actually trying to produce
    """
    c["time_in_phase"] = c["time_in_phase"] + dt

    # ==================================================================
    # TODO 1 -- move to the next phase when the current one is over
    #
    # The phases run in order:
    #     "cutting"   lasts RAMP_IN_MS
    #     "holding"   lasts HOLD_MS
    #     "restoring" lasts RAMP_OUT_MS
    #     then back to "idle"
    #
    # So: if the phase is "cutting" AND time_in_phase has passed
    # RAMP_IN_MS, change the phase to "holding" and set time_in_phase
    # back to 0.0. Then the same idea for the other two.
    #
    # WATCH OUT: RAMP_IN_MS is in milliseconds, time_in_phase is in
    # seconds. So compare against RAMP_IN_MS / 1000.0
    #
    # Write it with if / elif, like:
    #     if c["phase"] == "cutting" and c["time_in_phase"] >= ...:
    #         c["phase"] = "holding"
    #         c["time_in_phase"] = 0.0
    #     elif ...
    # ==================================================================

    # ==================================================================
    # TODO 2 -- what torque are we aiming for right now?
    #
    #   "idle"       -> driver_torque  (just pass the pedal through)
    #   "cutting"    -> ramp DOWN from c["torque_at_start"]
    #                   to c["target_torque"]
    #   "holding"    -> exactly c["target_torque"]
    #   "restoring"  -> ramp UP from c["target_torque"] to driver_torque
    #
    # Use the ramp() helper above. The fraction you are through a phase is
    #     c["time_in_phase"] / (PHASE_LENGTH_MS / 1000.0)
    # ==================================================================
    torque_target = driver_torque          # <-- replace this

    # ==================================================================
    # TODO 3 -- what spark angle produces that torque?
    #
    # The air has NOT changed during the shift, so spark has to do all of
    # the work. The fraction of torque we want is
    #     torque_target / c["torque_at_start"]
    #
    # Feed that to retard_for_fraction() to get the degrees, then
    #     spark = mbt - degrees
    #
    # When the phase is "idle", just use mbt (no retard at all).
    # ==================================================================
    spark = mbt                            # <-- replace this

    # ==================================================================
    # TODO 4 -- how much air do we ask for?  THE IMPORTANT ONE.
    #
    # While ANY shift phase is running (phase is not "idle"), the air
    # request must stay frozen at c["frozen_air"]. Do not tell the air
    # path about the cut. If you do, it opens the throttle to compensate,
    # the cut gets diluted, and torque overshoots badly when spark comes
    # back.
    #
    # When "idle", the air request is just driver_torque.
    #
    # If c["chase_air_bug"] is True, deliberately do the WRONG thing so
    # the simulation can show the failure:
    #     air_request = driver_torque / fraction_for_retard(mbt - spark)
    # ==================================================================
    air_request = driver_torque            # <-- replace this

    return spark, air_request, torque_target
