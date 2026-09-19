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

from tqmodel.model import (SPARK_EFF_K, SPARK_EFF_P, Engine, air_mass,
                           friction_torque, lambda_efficiency,
                           spark_efficiency)
from tqmodel.synth import truth_mbt, truth_ve
from tqmodel.units import ATM_KPA, KPA_PER_PSI, kpa_abs_to_boost_psi
from .connection import ECUConnection, ProtocolError
from .monitor import IDLE_ONLY, Monitor
from .table import check_axis

def _tools_dir() -> Path:
    """Where the shift coordinator lives.

    Running from the repo it is tools/ next to the package. Frozen, the
    bundle is read-only and the whole point of the coordinator is that the
    user edits it, so it is copied once into their own data directory and
    loaded from there.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[2] / "tools"
    import os
    import shutil
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    dst = root / "LambdaOne" / "tools"
    src = Path(getattr(sys, "_MEIPASS", ".")) / "tools"
    if not (dst / "shift" / "coordinator.py").exists() and src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


_TOOLS = _tools_dir()

GEAR_RATIOS = {1: 4.714, 2: 3.143, 3: 2.106, 4: 1.667, 5: 1.285, 6: 1.000, 7: 0.839, 8: 0.667}
ELEMENTS = "ABCDE"                       # A, B brakes; C, D, E clutches
ENGAGED = {1: "ABC", 2: "ABE", 3: "BCE", 4: "BDE", 5: "BCD", 6: "CDE", 7: "ACD", 8: "ADE"}
SHIFT_T = (0.10, 0.20, 0.45)             # fill done, torque phase done, inertia phase done (s)
P_MAX_BAR = 18.0
NM_PER_BAR = 38.0                        # display: element capacity per bar of apply pressure
PHASES = {"idle": 0, "cutting": 1, "holding": 2, "restoring": 3}


class SimulatedECU(ECUConnection):
    name = "Simulator"

    writable = True

    def __init__(self, tune):
        super().__init__()
        # The ECU holds its OWN image of the tune. The editor's copy reaches
        # it only through write_cell/write_table, exactly as it would over a
        # wire -- so an unsent edit cannot change how the engine runs.
        self.tune = tune.copy()
        self.flash = tune.copy()
        self.dt = 0.01
        self.pedal = 0.0                 # 0..1
        self.mode = "road"               # or "dyno"
        self.dyno_rpm = 3000.0
        self.chase_air_bug = False
        self._rng = np.random.default_rng(1)
        self.monitor = Monitor()
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
        self.rail = 5000.0
        self._rail_i = 0.0
        self.hpfp_duty = 0.0
        self.knock_retard = 0.0
        self.knock_count = 0
        self._knock_hold = 0.0
        self.step_error = None
        self.coord_fault = 0.0
        self._air_request = None
        self._driver_torque = 0.0
        self.shift_inhibit = 0.0
        self.monitor.reset()

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

    # ---- the table protocol -------------------------------------------
    def identify(self) -> dict:
        return {"ecu_id": "SIM-0001", "firmware": "simulator",
                "protocol_version": 1,
                "layout_hash": f"{self._layout_hash():08x}"}

    def _layout_hash(self) -> int:
        import zlib
        parts = []
        for k in sorted(self.tune.tables):
            t = self.tune.tables[k]
            parts.append(f"{k}:{t.n_x}x{t.n_y}:{t.lo}:{t.hi}")
        return zlib.crc32("|".join(parts).encode()) & 0xFFFFFFFF

    def describe_tables(self) -> dict:
        return {k: {"n_x": t.n_x, "n_y": t.n_y, "lo": t.lo, "hi": t.hi,
                    "unit": t.unit}
                for k, t in self.tune.tables.items()}

    def read_table(self, key: str):
        self._require_connected()
        t = self.tune.tables.get(key)
        if t is None:
            raise ProtocolError(f"no table {key!r} in this ECU")
        return t.values.copy()

    def write_cell(self, key: str, j: int, i: int, value: float):
        self._require_connected()
        t = self.tune.tables.get(key)
        if t is None:
            raise ProtocolError(f"no table {key!r} in this ECU")
        if not (0 <= j < t.n_y and 0 <= i < t.n_x):
            raise ProtocolError(f"{key}[{j},{i}] is outside the ECU layout "
                                f"({t.n_y}x{t.n_x})")
        if not t.accepts(value):
            raise ProtocolError(f"{key}: {value:g} is outside "
                                f"{t.lo:g}..{t.hi:g}")
        t.values[j, i] = float(value)
        # a real ECU echoes the committed value back; the tuner marks the
        # cell RAM only on the echo, never on the keystroke
        self.write_acked.emit(key, j, i, float(t.values[j, i]))

    def write_table(self, key: str, values, x=None, y=None):
        self._require_connected()
        t = self.tune.tables.get(key)
        if t is None:
            raise ProtocolError(f"no table {key!r} in this ECU")
        values = np.asarray(values, dtype=float)
        if values.shape != t.values.shape:
            raise ProtocolError(f"{key}: {values.shape} does not fit the ECU "
                                f"layout {t.values.shape}")
        t.check_bounds(values)
        if x is not None:
            t.x = check_axis(x, f"{key}.x")
        if y is not None:
            t.y = check_axis(y, f"{key}.y")
        t.values[:] = values

    def burn(self) -> dict:
        self._require_connected()
        self.tune.validate()
        self.flash = self.tune.copy()
        return self.flash.crcs()

    # ---- external controls --------------------------------------------------
    def request_shift(self, up=True):
        if self.mode != "road" or self.shift:
            return
        new = self.gear + (1 if up else -1)
        if not 1 <= new <= 8:
            return
        if self._would_overrev(new):
            self.shift_inhibit = 1.0     # a downshift the engine cannot survive
            return
        self.shift_inhibit = 0.0
        self._start_shift(new)

    def _would_overrev(self, new_gear: int) -> bool:
        """Engine speed the driveline would force after the shift. A manual
        downshift at speed is the classic way to put an engine past its
        limit, and the transmission must refuse it."""
        e = self.tune.engine
        fd = float(e.get("final_drive", 3.46))
        r_t = float(e.get("tire_radius_m", 0.318))
        wheel_rps = self.v / max(2 * math.pi * r_t, 1e-6)
        after = wheel_rps * 60.0 * fd * GEAR_RATIOS[new_gear]
        return after > float(e.get("rev_limit", 7200)) - 200.0

    def set_bug(self, on: bool):
        self.chase_air_bug = on
        if self.coord_state is not None:
            self.coord_state["chase_air_bug"] = on

    # ---- the plant --------------------------------------------------------
    # The engine on the dyno is NOT the engine the base map was written for.
    # These three surfaces are the truth the tuner is trying to find; the
    # tune's own VE, MBT and knock tables are only the current guess. If the
    # plant read the tune, every table would confirm itself and nothing
    # could be tuned.
    @staticmethod
    def plant_ve(rpm: float, map_kpa: float) -> float:
        err = (1.0 + 0.085 * math.sin(rpm / 1700.0)
               - 0.060 * max(map_kpa - 120.0, 0.0) / 120.0)
        return max(float(truth_ve(rpm, map_kpa)) * err, 0.05)

    @staticmethod
    def plant_mbt(rpm: float, map_kpa: float) -> float:
        return float(truth_mbt(rpm, map_kpa)) + 2.5 * math.cos(rpm / 2300.0) - 1.0

    @staticmethod
    def plant_spark_efficiency(delta_from_mbt: float) -> float:
        """Torque fraction either side of MBT, as the engine actually
        behaves.

        tqmodel.spark_efficiency is defined on retard only, and clips
        negative values to zero, because the ECU never deliberately
        commands more advance than MBT. The engine has no such rule. Push
        past MBT and peak pressure arrives too early, the rising piston
        fights it through the rest of compression, and torque falls
        again, faster than it does on the retarded side.

        Without this the sweep that finds MBT has no peak to find: over
        advancing would look free, and the curve would be a plateau
        running off to infinity.
        """
        d = float(delta_from_mbt)
        if d >= 0.0:
            return max(1.0 - SPARK_EFF_K * d ** SPARK_EFF_P, 0.0)
        over = -d
        # steeper the other way, and it is knocking by now in any case
        return max(1.0 - 2.2 * SPARK_EFF_K * over ** SPARK_EFF_P, 0.0)

    @staticmethod
    def plant_knock_limit(rpm: float, map_kpa: float) -> float:
        """Spark advance this engine will tolerate before it rattles."""
        return (26.0 - 0.26 * max(map_kpa - 90.0, 0.0)
                + 0.0016 * rpm + 2.0 * math.sin(rpm / 1900.0))

    def _fuel(self, air_g: float, lam_target: float, rpm: float,
              rail_kpa: float, cylinder_kpa: float):
        """Injected fuel and the pulse width that delivers it.

        Direct injection sprays into a cylinder that is itself under
        pressure, so what drives the nozzle is the DIFFERENCE between
        rail and cylinder, not the rail alone. At high load that
        difference is meaningfully smaller than the gauge reading, and an
        ECU that ignores it runs lean exactly when leanness hurts.

        Returns (fuel_mg, pw_ms, duty_pct).
        """
        e = self.tune.engine
        afr = float(e.get("afr_stoich", 14.7))
        fuel_g = air_g / max(afr * max(lam_target, 0.3), 1e-6)
        flow_cc_min = float(e.get("injector_flow_cc_min", 1050.0))
        rated = float(e.get("fuel_pressure_kpa", 350.0))
        dp = max(rail_kpa - cylinder_kpa, 50.0)
        flow_g_s = flow_cc_min / 60.0 * 0.745 * math.sqrt(dp / max(rated, 1.0))
        pw = fuel_g / max(flow_g_s, 1e-6) * 1000.0 + float(e.get("injector_deadtime_ms", 0.9))
        # Duty against the window injection can actually USE, not against
        # the whole cycle. A direct injector may only spray while the
        # intake valve is open and the cylinder is still low enough to
        # spray into; measuring it against 720 degrees makes the
        # injectors look about three times larger than they are, and the
        # first sign of that error on a real engine is a lean misfire at
        # full load.
        window_deg = float(e.get("inj_window_deg", 240.0))
        window_ms = window_deg / 360.0 * 60000.0 / max(rpm, 100.0)
        return fuel_g * 1000.0, pw, min(pw / max(window_ms, 1e-6) * 100.0, 100.0)

    def _rail_step(self, dt: float, target_kpa: float, demand_g_s: float,
                   rpm: float):
        """Rail pressure: on target while the pump can keep up, drooping
        when it cannot.

        Fuel is stiff. A gram of imbalance in a twenty cc rail moves the
        pressure by tens of thousands of kPa, which is why real pump
        control is fast, angle-scheduled and closed loop. Simulating that
        loop tick by tick at a hundred hertz would model its numerical
        problems rather than the engine's, and the loop is the ECU's job
        and it works. What the tuner needs to see is the part that does
        not work: when the injectors draw more than the pump can deliver,
        the rail falls, every pulse delivers less than planned, and the
        engine goes lean at exactly the worst moment.

        So the loop is modelled by its outcome. Within capacity the rail
        tracks its target with the lag a real system has. Beyond it, the
        rail settles where the pump's delivery balances the draw.
        """
        e = self.tune.engine
        cap = float(e.get("hpfp_capacity_g_s", 22.0))
        # the pump is driven off the camshaft, so it delivers nothing
        # until the engine turns and reaches full stroke rate with speed
        cap *= min(max(rpm / 1200.0, 0.0), 1.0)

        if demand_g_s <= cap and cap > 0.0:
            self.hpfp_duty = demand_g_s / cap
            reachable = target_kpa
        else:
            # Out of capacity. Flow through the nozzle goes as the square
            # root of the pressure drop, so the rail falls to where the
            # injectors can only pass what the pump supplies.
            self.hpfp_duty = 1.0
            shortfall = cap / max(demand_g_s, 1e-6)
            reachable = max(target_kpa * shortfall * shortfall, 300.0)

        tau = 0.08
        self.rail += (reachable - self.rail) * min(dt / tau, 1.0)
        self.rail = min(max(self.rail, 300.0), 25000.0)
        return self.hpfp_duty

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
        # any shift that actually starts clears a stale inhibit marker
        self.shift_inhibit = 0.0
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
            try:
                self._step()
            except Exception as exc:                  # noqa: BLE001
                # One bad tune or one bad line of model code must not turn
                # into a hundred tracebacks a second. Stop, say why, once.
                self._timer.stop()
                self.step_error = f"{type(exc).__name__}: {exc}"
                self.error.emit(f"Simulation stopped: {self.step_error}")
                self._acc = 0.0
                return
            self._acc -= self.dt; n += 1
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
        # a boost target is a request, not a permission: the wastegate can
        # only be asked for what the hardware limit allows
        boost_max = float(e.get("boost_max_kpa", 240.0)) - ATM_KPA
        boost_tgt = min(boost_tgt, max(boost_max, 0.0))
        spool = min(max((self.rpm - 1800.0) / 1800.0, 0.0), 1.0)      # no exhaust energy, no boost
        boost_t = boost_tgt * spool
        self._last_targets = (map_na_t, boost_t)
        # the air freeze belongs to the sim's shift window, never to the
        # coordinator's own state -- an unfinished coordinator that never
        # returns to idle must not be able to wedge the air path
        if self.shift is not None and self.frozen is not None:
            ar = self._air_request
            if ar is not None and math.isfinite(ar) and self._driver_torque > 1.0:
                # the COORDINATOR owns the freeze: whatever air it asks for
                # is what the throttle and wastegate are sized for. Holding
                # the pre-shift request means scale 1.0; chasing the cut
                # means asking for more, and the overshoot that follows is
                # the lesson.
                k = min(max(ar / self._driver_torque, 0.3), 1.6)
                map_na_t = self.frozen[0]
                boost_t = min(self.frozen[1] * k, 30.0 * KPA_PER_PSI)
            elif self.chase_air_bug:
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

        # ---- charge, fuel, spark, torque ----------------------------------------
        # What the ECU BELIEVES: its VE table, used to size the injection.
        ve_cmd = T["ve"].lookup(self.rpm, map_kpa)
        air_cmd = float(air_mass(ve_cmd, map_kpa, t_charge, eng))
        lam_target = T["lambda"].lookup(self.rpm, map_kpa)
        rail_target = T["rail_target"].lookup(self.rpm, map_kpa)
        fuel_mg, pw_ms, duty = self._fuel(air_cmd, lam_target, self.rpm,
                                          self.rail, map_kpa)
        # what the injectors are about to draw, in grams per second
        demand_g_s = (fuel_mg * 1e-3 * float(e.get("n_cyl", 4))
                      * self.rpm / 120.0)
        self._rail_step(dt, rail_target, demand_g_s, self.rpm)
        rail_kpa = self.rail
        soi = T["soi"].lookup(self.rpm, map_kpa)
        split = T["inj_split"].lookup(self.rpm, map_kpa)
        n_pulses = 2 if split > 0.01 else 1

        # What the ENGINE actually does: the plant's own VE. The difference
        # between the two is exactly what shows up in measured lambda, which
        # is what makes the VE table tunable.
        ve_true = self.plant_ve(self.rpm, map_kpa)
        air = float(air_mass(ve_true, map_kpa, t_charge, eng))
        afr = float(e.get("afr_stoich", 14.7))
        lam = air / max(fuel_mg * 1e-3 * afr, 1e-9)
        lam = min(max(lam, 0.4), 2.5) + float(self._rng.normal(0, 0.004))

        mbt = self.plant_mbt(self.rpm, map_kpa)          # the real peak
        mbt_tbl = T["mbt"].lookup(self.rpm, map_kpa)     # where the tune thinks it is
        knock_tbl = T["knock"].lookup(self.rpm, map_kpa)
        spark_cmd = min(mbt_tbl, knock_tbl) - 1.0                 # 1 degree of margin

        # ---- knock ---------------------------------------------------------------
        # The plant has its own detonation threshold. Command more advance
        # than that and it knocks, the ECU hears it and pulls timing back.
        limit = self.plant_knock_limit(self.rpm, map_kpa)
        if spark_cmd - self.knock_retard > limit and self.rpm > 1200.0:
            self.knock_count += 1
            self.knock_retard = min(self.knock_retard + 1.5, 15.0)
            self._knock_hold = 1.5
        self._knock_hold = max(self._knock_hold - dt, 0.0)
        if self._knock_hold <= 0.0:
            self.knock_retard = max(self.knock_retard - 0.6 * dt, 0.0)
        spark_base = spark_cmd - self.knock_retard
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
            # The coordinator is the user's own code. It gets the current
            # operating spark as its reference, so its retard is relative to
            # where spark actually sits, knock retard already spent included.
            # It is untrusted: anything it returns is clamped, and an
            # exception in it must not be able to stop the engine.
            try:
                sp_cmd, air_req, torque_target = self.coord.update(
                    self.coord_state, dt, t_req, spark_base)
                if not (math.isfinite(sp_cmd) and math.isfinite(torque_target)):
                    raise ValueError("coordinator returned a non-finite value")
                max_cut = float(e.get("max_cut_retard", 35.0))
                sp_cmd = min(max(sp_cmd, spark_base - max_cut), spark_base)
                self.coord_fault = 0.0
            except Exception as exc:                  # noqa: BLE001
                self.coord_error = f"{type(exc).__name__}: {exc}"
                self.coord = None                     # stop calling it
                self.coord_fault = 1.0
                sp_cmd, air_req, torque_target = spark_base, t_req, t_req
            if self.shift is not None:
                spark = min(spark_base, sp_cmd)
                self._air_request = air_req
            else:
                torque_target = t_req
                self._air_request = None
        t_ind = base * self.plant_spark_efficiency(mbt - spark) * lam_eff
        t_brake = t_ind - t_fric
        if pedal < 0.03:
            # idle speed control: a real governor produces no net torque above
            # its target speed, whatever the manifold pressure says
            t_brake = min(t_brake, max(0.0, (900.0 - self.rpm) * 0.08))
            t_req = min(t_req, max(0.0, (900.0 - self.rpm) * 0.08))
        overrun = pedal < 0.03 and self.rpm > 1250.0
        rev_limit = float(e.get("rev_limit", 7200))
        overboost_kpa = float(e.get("overboost_cut_kpa", 265.0))
        overboost = map_kpa > overboost_kpa
        if self.rpm > rev_limit or overrun or overboost:
            t_brake = -t_fric                    # fuel cut: limiter, overrun or overboost

        # ---- Level 2 monitor -----------------------------------------------------
        # Two pedal tracks and two throttle tracks, as the hardware has. The
        # monitor never sees the torque model's own numbers.
        noise = float(self._rng.normal(0, 0.15))
        pedal_a, pedal_b = tps, tps + noise
        tps_a, tps_b = tps + noise, tps
        # The ceiling the engine could reach at this speed, not what it
        # happens to be making. Feeding the monitor the current value
        # would have it compare torque against a function of itself.
        max_torque = max(float(T["base_torque"].lookup(self.rpm,
                                                       T["base_torque"].y[-1]))
                         - t_fric, 1.0)
        limp, fault = self.monitor.update(
            dt, pedal_a, pedal_b, tps_a, tps_b, tps, t_brake, self.rpm,
            max_torque, rev_limit, map_kpa, overboost_kpa)
        if limp != 0:
            t_brake = min(t_brake, self.monitor.torque_cap(max_torque))
        # fast-path authority: down to 30 degrees from MBT, not from wherever
        # spark is now -- knock retard already spent counts against it
        floor = base * float(spark_efficiency(30.0)) * lam_eff - t_fric
        authority = max(t_brake - floor, 0.0) if not overrun else 0.0
        self._spark, self._mbt = spark, mbt
        self._driver_torque = t_req

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
                # Through request_shift, not straight to _start_shift:
                # an automatic downshift can put the engine past its
                # limit just as easily as a manual one, and the guard
                # belongs on both paths or neither.
                if self.gear < 8 and turbine > up:
                    self.request_shift(True)
                elif self.gear > 1 and turbine < down:
                    self.request_shift(False)

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
                  clt=self.clt, iat=self.iat, spark=spark, mbt=mbt_tbl,
                  knock=knock_tbl,
                  torque=t_brake, torque_req=torque_target, authority=authority,
                  cut_deg=max(spark_base - spark, 0.0), overrun=float(overrun),
                  batt=13.8 + float(self._rng.normal(0, 0.02)), air=air, ve=ve_true,
                  gear=float(self.gear), ratio=ratio_g, turbine_rpm=turbine,
                  output_rpm=self.v / (2 * math.pi * r_t) * 60.0 * fd, speed=self.v * 3.6,
                  line_bar=line, tc_lock=float(tc_lock), shift_phase=float(phase),
                  coord_phase=float(PHASES.get(self.coord_state["phase"], 0)) if self.coord_state else 0.0,
                  shift_from=float(self.shift["old"]) if self.shift else 0.0,
                  shift_to=float(self.shift["new"]) if self.shift else 0.0,
                  pw_ms=pw_ms, inj_duty=duty, fuel_mass=fuel_mg, rail_kpa=rail_kpa,
                  rail_target=rail_target, rail_error=rail_kpa - rail_target,
                  hpfp_duty=self.hpfp_duty * 100.0, soi=soi,
                  inj_split=split, inj_pulses=float(n_pulses),
                  knock_retard=self.knock_retard, knock_count=float(self.knock_count),
                  pedal_a=pedal_a, pedal_b=pedal_b, tps_a=tps_a, tps_b=tps_b,
                  torque_permissible=self.monitor.permissible,
                  monitor_state=float(self.monitor.state),
                  limp_level=float(self.monitor.limp),
                  fault_code=float(self.monitor.fault),
                  coord_fault=self.coord_fault,
                  shift_inhibit=self.shift_inhibit)
        ch["lambda"] = lam
        for el in ELEMENTS:
            ch[f"p_{el.lower()}"] = self.p[el]
