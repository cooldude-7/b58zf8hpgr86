"""Independent torque monitor: the Level 2 half of the three-level concept.

Level 1 is the function code (torque structure, air path, spark). Level 2
is this: it recomputes, from its own sensor reads and its own simple model,
how much torque the driver could possibly be asking for, and compares it to
what Level 1 is actually producing. If Level 1 makes more torque than the
driver asked for, something is wrong and the engine is brought down. Level
3 is the watchdog that checks Level 2 is still running, and lives in
firmware where there is a second core to run it on.

Written in plain Python with no Qt and no numpy so it ports to C as-is:
integer state, float compare, no allocation.
"""

# Limp levels, in increasing severity.
OK, REDUCED, IDLE_ONLY, SHUTDOWN = 0, 1, 2, 3

# Fault codes. Numbers are stable; they end up in a log and a scan tool.
F_NONE = 0
F_PEDAL_PLAUSIBILITY = 1
F_TPS_PLAUSIBILITY = 2
F_TORQUE_EXCEEDS_PERMISSIBLE = 3
F_TPS_TRACKING = 4
F_OVERSPEED = 5
F_OVERBOOST = 6

# Thresholds. A real calibration puts these in the tune; they are constants
# here because changing them is a safety decision, not a tuning one.
PEDAL_DISAGREE_PCT = 10.0       # two pedal tracks may differ by this much
TPS_DISAGREE_PCT = 8.0
TPS_TRACKING_PCT = 15.0         # commanded vs measured throttle
DEBOUNCE_S = 0.10               # a fault must persist this long to act
TORQUE_MARGIN_NM = 30.0         # permissible torque headroom before limp
TORQUE_DEBOUNCE_S = 0.20


class Monitor:
    """One instance per engine. Call update() every fast-task cycle."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = OK
        self.fault = F_NONE      # the FIRST fault seen: the root cause
        self.faults = []         # every distinct fault, in the order they appeared
        self.limp = OK
        self._t_pedal = 0.0
        self._t_tps = 0.0
        self._t_track = 0.0
        self._t_torque = 0.0
        self.permissible = 0.0

    def permissible_torque(self, pedal_pct: float, rpm: float,
                           max_torque: float) -> float:
        """What the driver could be asking for, computed the simple way and
        deliberately NOT from the same tables Level 1 uses. Idle creep is
        allowed at zero pedal; above that it is a straight ramp."""
        p = max(0.0, min(pedal_pct, 100.0)) / 100.0
        idle_allowance = 40.0 if rpm < 1500.0 else 15.0
        return idle_allowance + p * max_torque

    def update(self, dt: float, pedal_a: float, pedal_b: float,
               tps_a: float, tps_b: float, tps_cmd: float,
               torque: float, rpm: float, max_torque: float,
               rev_limit: float, map_kpa: float, overboost_kpa: float):
        """Returns (limp_level, fault_code). Level 1 must obey the limp
        level; this function never touches an actuator itself."""
        fault = F_NONE

        self._t_pedal = self._t_pedal + dt if abs(pedal_a - pedal_b) > PEDAL_DISAGREE_PCT else 0.0
        self._t_tps = self._t_tps + dt if abs(tps_a - tps_b) > TPS_DISAGREE_PCT else 0.0
        self._t_track = self._t_track + dt if abs(tps_cmd - tps_a) > TPS_TRACKING_PCT else 0.0

        # With a pedal fault the lower of the two tracks is the safe read.
        pedal = min(pedal_a, pedal_b) if self._t_pedal > DEBOUNCE_S else pedal_a
        self.permissible = self.permissible_torque(pedal, rpm, max_torque)
        over = torque > self.permissible + TORQUE_MARGIN_NM
        self._t_torque = self._t_torque + dt if over else 0.0

        limp = OK
        if self._t_pedal > DEBOUNCE_S:
            fault, limp = F_PEDAL_PLAUSIBILITY, REDUCED
        if self._t_tps > DEBOUNCE_S:
            fault, limp = F_TPS_PLAUSIBILITY, IDLE_ONLY
        if self._t_track > DEBOUNCE_S:
            fault, limp = F_TPS_TRACKING, IDLE_ONLY
        if self._t_torque > TORQUE_DEBOUNCE_S:
            fault, limp = F_TORQUE_EXCEEDS_PERMISSIBLE, IDLE_ONLY
        if rpm > rev_limit + 500.0:
            fault, limp = F_OVERSPEED, SHUTDOWN
        if map_kpa > overboost_kpa:
            fault, limp = F_OVERBOOST, SHUTDOWN

        # A monitor that clears itself the instant the symptom goes away is
        # a monitor that lets an intermittent fault run the engine. Once a
        # limp is entered it stays until reset() (key cycle).
        if fault != F_NONE and fault not in self.faults:
            self.faults.append(fault)
            if self.fault == F_NONE:
                self.fault = fault       # keep the root cause, not the last symptom
        if limp > self.limp:
            self.limp = limp
        self.state = self.limp
        return self.limp, self.fault

    def torque_cap(self, max_torque: float) -> float:
        """The ceiling Level 1 must respect at the current limp level."""
        if self.limp == OK:
            return max_torque
        if self.limp == REDUCED:
            return 0.5 * max_torque
        if self.limp == IDLE_ONLY:
            return 30.0
        return 0.0
