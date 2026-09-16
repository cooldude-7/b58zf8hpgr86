"""Simulated engine, driveline and ZF 8HP behind the ECUConnection interface.

Runs on a 100 Hz QTimer in the main thread: each step is a handful of table
lookups, far cheaper than the repaints it drives. It reads the LIVE tune --
edit the VE table and the engine changes on the next step, like controller
RAM. "Burn" is bookkeeping that clears the dirty markers.

This is deliberately not a vehicle-dynamics thesis. It has enough physics
that the engine responds to the tune, the pedal and the shift coordinator
in ways a tuner recognises, and every simplification is named where it is
made.
"""
import importlib
import math
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QElapsedTimer, Qt, QTimer

from tqmodel.model import (Engine, air_mass, friction_torque, lambda_efficiency,
                           spark_efficiency)
from tqmodel.units import ATM_KPA, KPA_PER_PSI, kpa_abs_to_boost_psi
from .connection import ECUConnection

_TOOLS = Path(__file__).resolve().parents[2] / "tools"

GEAR_RATIOS = {1: 4.714, 2: 3.143, 3: 2.106, 4: 1.667, 5: 1.285, 6: 1.000, 7: 0.839, 8: 0.667}
ELEMENTS = "ABCDE"                       # A, B brakes; C, D, E clutches
ENGAGED = {1: "ABC", 2: "ABE", 3: "BCE", 4: "BDE", 5: "BCD", 6: "CDE", 7: "ACD", 8: "ADE"}
SHIFT_T = (0.10, 0.20, 0.45)             # fill done, torque phase done, inertia phase done (s)
P_MAX_BAR = 18.0
NM_PER_BAR = 38.0                        # display: element capacity per bar of apply pressure
PHASES = {"idle": 0, "cutting": 1, "holding": 2, "restoring": 3}


class SimulatedECU(ECUConnection):
    name = "Simulator"

    def __init__(self, tune):
        super().__init__()
        self.tune = tune
        self.dt = 0.01
        self.pedal = 0.0                 # 0..1
        self.mode = "road"               # or "dyno"
        self.dyno_rpm = 3000.0
        self.chase_air_bug = False
        self._rng = np.random.default_rng(1)
        self.reset()
        self.coord = self.coord_state = self.coord_error = None
        self.load_coordinator()
        # The timer is a wake-up, not the clock: repaints can delay it badly,
        # so each tick runs as many fixed steps as wall-clock time demands.
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._acc = 0.0
        self._since_publish = 0.0

    def reset(self):
        self.t = 0.0
        self.rpm, self.map_na, self.boost = 850.0, 35.0, 0.0
        self.v, self.gear = 0.0, 1
        self.clt, self.iat = 20.0, 25.0
        self.p = {e: 0.0 for e in ELEMENTS}
        self.shift = None                # dict(t, old, new) while a shift is in progress
        self.frozen = None               # (map_na_target, boost_target) held during a cut
        self._last_targets = (35.0, 0.0)
        self._spark, self._mbt = 20.0, 20.0
        self.tc_lock = 0

    # ---- the coordinator exercise --------------------------------------
    def load_coordinator(self):
        """Import tools/shift/coordinator.py -- the user's own control code."""
        if str(_TOOLS) not in sys.path:
            sys.path.insert(0, str(_TOOLS))
        try:
            import shift.coordinator as c
            self.coord = importlib.reload(c)
            self.coord_state = self.coord.new_controller()
            self.coord_state["chase_air_bug"] = self.chase_air_bug
            self.coord_error = None
        except Exception as e:                       # noqa: BLE001 -- surface it in the UI
            self.coord, self.coord_state, self.coord_error = None, None, str(e)

    # ---- connection -------------------------------------------------------
    def connect_ecu(self):
        self._clock.start(); self._acc = 0.0; self._since_publish = 0.0
        self._timer.start()
        super().connect_ecu()

    def disconnect_ecu(self):
        self._timer.stop()
        self._channels = {k: 0.0 for k in self._channels}
        self.channels_updated.emit(self.channels())
        super().disconnect_ecu()

    # ---- external controls --------------------------------------------------
    def request_shift(self, up=True):
        if self.mode != "road" or self.shift:
            return
        new = self.gear + (1 if up else -1)
        if 1 <= new <= 8:
            self._start_shift(new)

    def set_bug(self, on: bool):
        self.chase_air_bug = on
        if self.coord_state is not None:
            self.coord_state["chase_air_bug"] = on

    # ---- engine constants from the tune --------------------------------------
    def _engine(self) -> Engine:
        e = self.tune.engine
        cf = e.get("chen_flynn", [0.4, 0.005, 0.09, 0.0009])
        return Engine(n_cyl=int(e.get("n_cyl", 4)), displacement_l=float(e.get("displacement_l", 2.0)),
                      compression_ratio=float(e.get("compression_ratio", 11.0)),
                      afr_stoich=float(e.get("afr_stoich", 14.7)), stroke_m=float(e.get("stroke_m", 0.094)),
                      cf_a=cf[0], cf_b=cf[1], cf_c=cf[2], cf_d=cf[3])

    # ---- shifting ---------------------------------------------------------------
    def _start_shift(self, new_gear):
        self.shift = dict(t=0.0, old=self.gear, new=new_gear)
        self.frozen = self._last_targets
        if self.coord is not None:
            t_now = self._channels.get("torque", 0.0)
            t_req = self._channels.get("torque_req", t_now)
            cut_to = max(t_req * (0.35 if new_gear > self.gear else 0.6), 0.0)
            self.coord.start_shift(self.coord_state, cut_to, max(t_now, 1.0))

    # ---- physics ------------------------------------------------------------------
    def _tick(self):
        elapsed = self._clock.restart() / 1000.0
        self._acc += min(elapsed, 0.25)            # a long stall (debugger, sleep) is dropped, not replayed
        n = 0
        while self._acc >= self.dt and n < 25:
            self._step(); self._acc -= self.dt; n += 1
        self._since_publish += elapsed
        if self._since_publish >= 0.04:             # publish at 25 Hz
            self._since_publish = 0.0
            self.channels_updated.emit(self.channels())

    def _step(self):
        dt = self.dt
        e = self.tune.engine
        eng = self._engine()
        T = self.tune.tables
        self.t += dt
        pedal = min(max(self.pedal, 0.0), 1.0)
        tps = pedal * 100.0

        # ---- air path: throttle part (fast) plus boost part (turbo lag) ---------
        map_na_t = 30.0 + 71.0 * (1.0 - (1.0 - pedal) ** 2)
        if pedal < 0.03:
            # idle governor: trim manifold pressure to hold ~850 rpm in gear
            map_na_t = min(max(30.0 - 0.03 * (self.rpm - 850.0), 20.0), 40.0)
        boost_tgt = max(0.0, T["boost"].lookup(self.rpm, tps)) * KPA_PER_PSI if "boost" in T else 0.0
        spool = min(max((self.rpm - 1800.0) / 1800.0, 0.0), 1.0)      # no exhaust energy, no boost
        boost_t = boost_tgt * spool
        self._last_targets = (map_na_t, boost_t)
        # the air freeze belongs to the sim's shift window, never to the
        # coordinator's own state -- an unfinished coordinator that never
        # returns to idle must not be able to wedge the air path
        if self.shift is not None and self.frozen is not None:
            if self.chase_air_bug:
                # an air path that does not know the cut is deliberate chases it
                eff_now = max(float(spark_efficiency(self._mbt - self._spark)), 0.05)
                map_na_t, boost_t = self.frozen[0], min(self.frozen[1] / eff_now, 30.0 * KPA_PER_PSI)
            else:
                map_na_t, boost_t = self.frozen
        self.map_na += (map_na_t - self.map_na) * dt / 0.12
        self.boost += (boost_t - self.boost) * dt / 0.70
        map_kpa = self.map_na + self.boost * min(1.0, pedal * 1.5)
        map_kpa = min(max(map_kpa, 20.0), ATM_KPA + 30.0 * KPA_PER_PSI)

        # ---- thermal ------------------------------------------------------------
        self.clt += (90.0 - self.clt) * dt / 90.0
        self.iat = 25.0 + 0.12 * max(map_kpa - ATM_KPA, 0.0)
        t_charge = 273.15 + self.iat + 15.0

        # ---- charge, spark, lambda, torque --------------------------------------
        ve = T["ve"].lookup(self.rpm, map_kpa)
        air = float(air_mass(ve, map_kpa, t_charge, eng))
        mbt = T["mbt"].lookup(self.rpm, map_kpa)
        knock = T["knock"].lookup(self.rpm, map_kpa)
        spark_base = min(mbt, knock) - 1.0                       # 1 degree of margin
        lam = T["lambda"].lookup(self.rpm, map_kpa) + float(self._rng.normal(0, 0.004))
        # friction (Chen-Flynn), accessories, and pumping work against a closed
        # throttle -- the model's FMEP term does not include pumping
        vd_m3 = float(e.get("displacement_l", 2.0)) * 1e-3
        t_pump = max(ATM_KPA - map_kpa, 0.0) * 1e3 * vd_m3 / (4.0 * math.pi)
        t_fric = float(friction_torque(self.rpm, map_kpa, eng)) + 5.0 + t_pump
        base = T["base_torque"].lookup(self.rpm, air)              # x = rpm, y = air mass
        lam_eff = float(lambda_efficiency(lam))
        t_req = base * float(spark_efficiency(mbt - spark_base)) * lam_eff - t_fric

        spark, torque_target = spark_base, t_req
        if self.coord is not None:
            # the coordinator is given the knock-limited base as its "MBT":
            # its retard is then relative to where spark actually sits
            sp_cmd, _air_req, torque_target = self.coord.update(self.coord_state, dt, t_req, spark_base)
            if self.shift is not None:
                spark = min(spark_base, sp_cmd)
            else:
                torque_target = t_req
        t_ind = base * float(spark_efficiency(mbt - spark)) * lam_eff
        t_brake = t_ind - t_fric
        if pedal < 0.03:
            # idle speed control: a real governor produces no net torque above
            # its target speed, whatever the manifold pressure says
            t_brake = min(t_brake, max(0.0, (900.0 - self.rpm) * 0.08))
            t_req = min(t_req, max(0.0, (900.0 - self.rpm) * 0.08))
        overrun = pedal < 0.03 and self.rpm > 1250.0
        if self.rpm > float(e.get("rev_limit", 7200)) or overrun:
            t_brake = -t_fric                                    # fuel cut: limiter or overrun
        # fast-path authority: down to 30 degrees from MBT, not from wherever
        # spark is now -- knock retard already spent counts against it
        floor = base * float(spark_efficiency(30.0)) * lam_eff - t_fric
        authority = max(t_brake - floor, 0.0) if not overrun else 0.0
        self._spark, self._mbt = spark, mbt

        # ---- driveline -----------------------------------------------------------
        fd = float(e.get("final_drive", 3.46))
        r_t = float(e.get("tire_radius_m", 0.318))
        m = float(e.get("vehicle_mass_kg", 1400.0))
        ratio_g = GEAR_RATIOS[self.gear]
        ratio_eff = ratio_g * fd
        phase = 0
        if self.mode == "dyno":
            # a dyno brake holding a setpoint; the car is a formality
            self.rpm += max(min((self.dyno_rpm - self.rpm) * dt / 0.35, 3000.0 * dt), -3000.0 * dt)
            self.rpm = max(self.rpm, 800.0)
            self.v = self.rpm / ratio_eff * 2 * math.pi * r_t / 60.0
            tc_lock, turbine = 1, self.rpm
        else:
            if self.shift:
                s = self.shift
                s["t"] += dt
                old, new = GEAR_RATIOS[s["old"]] * fd, GEAR_RATIOS[s["new"]] * fd
                if s["t"] < SHIFT_T[1]:
                    ratio_eff, phase = old, (1 if s["t"] < SHIFT_T[0] else 2)
                elif s["t"] < SHIFT_T[2]:
                    f = (s["t"] - SHIFT_T[1]) / (SHIFT_T[2] - SHIFT_T[1])
                    ratio_eff, phase = old + (new - old) * f, 3
                else:
                    self.gear, self.shift, ratio_eff, self.frozen = s["new"], None, new, None
                    if self.coord_state is not None:
                        self.coord_state["phase"] = "idle"      # heal a coordinator that never finished
            wheel_rpm = self.v / (2 * math.pi * r_t) * 60.0
            turbine = wheel_rpm * ratio_eff                     # turbine is geared to the wheels
            sr = min(turbine / max(self.rpm, 1.0), 1.0)         # speed ratio, turbine / pump
            # lock-up with hysteresis, once the converter is near coupling
            if self.tc_lock and turbine < 1200.0:
                self.tc_lock = 0
            elif not self.tc_lock and turbine > 1400.0 and sr > 0.85:
                self.tc_lock = 1
            tc_lock = self.tc_lock
            if tc_lock:
                t_turbine = t_brake
                self.rpm = turbine
            else:
                # pump absorption rises with speed squared; its capacity holds
                # until the turbine is well caught up, then tails off toward
                # coupling but never to nothing -- so the engine cannot run
                # away from the turbine. Multiplication is 1.6 at stall, 1.0
                # by coupling.
                f_sr = 1.0 if sr < 0.6 else max(1.0 - ((sr - 0.6) / 0.4) ** 2, 0.12)
                t_pump_abs = 4.4e-5 * self.rpm ** 2 * f_sr
                # the converter can only pass on what the engine actually makes
                t_turbine = min(t_pump_abs, max(t_brake, 0.0)) * (1.6 - 0.6 * min(sr / 0.85, 1.0))
                if t_brake < 0:                                 # overrun: engine dragged by the wheels
                    t_turbine = t_brake * sr
                rpm_dot = (t_brake - t_pump_abs) / 0.35 * 60.0 / (2 * math.pi)
                self.rpm = min(max(self.rpm + rpm_dot * dt, 800.0), float(e.get("rev_limit", 7200)) + 300.0)
            wheel_torque = t_turbine * ratio_eff * 0.92
            traction = 0.95 * m * 9.81 * 0.58                    # rear axle share on a decent tyre
            force = min(max(wheel_torque / r_t, -traction), traction)
            road = 0.015 * m * 9.81 + 0.5 * 1.2 * 0.75 * self.v ** 2
            a = (force - road) / (m * 1.08)
            self.v = max(self.v + a * dt, 0.0)
            if not self.shift and self.v > 2.0:
                up, down = 2200.0 + 4800.0 * pedal, 1400.0 + 2100.0 * pedal
                if self.gear < 8 and turbine > up:
                    self._start_shift(self.gear + 1)
                elif self.gear > 1 and turbine < down:
                    self._start_shift(self.gear - 1)

        # ---- shift element pressures ---------------------------------------------
        line = 4.0 + 14.0 * min(max(t_brake / 450.0, 0.0), 1.0)
        targets = {el: (line if el in ENGAGED[self.gear] else 0.0) for el in ELEMENTS}
        if self.shift:
            s, tt = self.shift, self.shift["t"]
            on = set(ENGAGED[s["new"]]) - set(ENGAGED[s["old"]])
            off = set(ENGAGED[s["old"]]) - set(ENGAGED[s["new"]])
            f_fill = min(tt / SHIFT_T[0], 1.0)
            f_tq = min(max((tt - SHIFT_T[0]) / (SHIFT_T[1] - SHIFT_T[0]), 0.0), 1.0)
            for el in on:
                targets[el] = line * (0.35 * f_fill if tt < SHIFT_T[0] else 0.35 + 0.65 * f_tq)
            for el in off:
                targets[el] = line * (1.0 if tt < SHIFT_T[0] else 1.0 - f_tq)
        for el in ELEMENTS:
            self.p[el] += (targets[el] - self.p[el]) * dt / 0.04

        # ---- publish -------------------------------------------------------------
        ch = self._channels
        ch.update(rpm=self.rpm, map=map_kpa, boost=kpa_abs_to_boost_psi(map_kpa), tps=tps,
                  clt=self.clt, iat=self.iat, spark=spark, mbt=mbt, knock=knock,
                  torque=t_brake, torque_req=torque_target, authority=authority,
                  batt=13.8 + float(self._rng.normal(0, 0.02)), air=air, ve=ve,
                  gear=float(self.gear), ratio=ratio_g, turbine_rpm=turbine,
                  output_rpm=self.v / (2 * math.pi * r_t) * 60.0 * fd, speed=self.v * 3.6,
                  line_bar=line, tc_lock=float(tc_lock), shift_phase=float(phase),
                  coord_phase=float(PHASES.get(self.coord_state["phase"], 0)) if self.coord_state else 0.0,
                  shift_from=float(self.shift["old"]) if self.shift else 0.0,
                  shift_to=float(self.shift["new"]) if self.shift else 0.0)
        ch["lambda"] = lam
        for el in ELEMENTS:
            ch[f"p_{el.lower()}"] = self.p[el]
