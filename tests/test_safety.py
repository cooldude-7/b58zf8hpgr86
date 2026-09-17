"""Everything that has to hold before this code goes anywhere near an engine.

These are not feature tests. Each one corresponds to a way the engine could
be damaged or the car could behave unexpectedly, and each must keep passing
for the firmware port to be worth starting.
"""
import math

import pytest

from tuner.core.monitor import (F_OVERBOOST, F_OVERSPEED, F_PEDAL_PLAUSIBILITY,
                                F_TORQUE_EXCEEDS_PERMISSIBLE, F_TPS_PLAUSIBILITY,
                                IDLE_ONLY, OK, REDUCED, SHUTDOWN, Monitor)


def run(m, n, **kw):
    args = dict(dt=0.01, pedal_a=50.0, pedal_b=50.0, tps_a=50.0, tps_b=50.0,
                tps_cmd=50.0, torque=100.0, rpm=3000.0, max_torque=400.0,
                rev_limit=7200.0, map_kpa=150.0, overboost_kpa=265.0)
    args.update(kw)
    for _ in range(n):
        out = m.update(**args)
    return out


# ---- the Level 2 monitor --------------------------------------------------
def test_nominal_driving_raises_nothing():
    assert run(Monitor(), 200) == (OK, 0)


def test_pedal_disagreement_is_caught():
    m = Monitor()
    limp, _ = run(m, 30, pedal_a=80.0, pedal_b=10.0, torque=50.0)
    assert limp >= REDUCED
    assert m.fault == F_PEDAL_PLAUSIBILITY


def test_pedal_disagreement_must_persist_to_act():
    """A single noisy sample is not a fault. Debounce is what keeps a car
    from limping because of one bad ADC read."""
    m = Monitor()
    limp, _ = run(m, 2, pedal_a=80.0, pedal_b=10.0)
    assert limp == OK


def test_throttle_disagreement_drops_to_idle_only():
    m = Monitor()
    limp, _ = run(m, 30, tps_a=80.0, tps_b=10.0, tps_cmd=80.0)
    assert limp >= IDLE_ONLY
    assert m.fault == F_TPS_PLAUSIBILITY


def test_throttle_not_tracking_its_command_is_caught():
    m = Monitor()
    limp, _ = run(m, 30, tps_cmd=90.0, tps_a=20.0, tps_b=20.0)
    assert limp >= IDLE_ONLY


def test_more_torque_than_the_driver_asked_for_is_caught():
    """The core of the torque monitor: the engine making power nobody
    requested is the failure that runs a car into a wall."""
    m = Monitor()
    limp, _ = run(m, 40, pedal_a=0.0, pedal_b=0.0, tps_a=0.0, tps_b=0.0,
                  tps_cmd=0.0, torque=390.0)
    assert limp >= IDLE_ONLY
    assert m.fault == F_TORQUE_EXCEEDS_PERMISSIBLE


def test_idle_torque_is_allowed_at_zero_pedal():
    limp, _ = run(Monitor(), 60, pedal_a=0.0, pedal_b=0.0, tps_a=0.0,
                  tps_b=0.0, tps_cmd=0.0, torque=35.0, rpm=800.0)
    assert limp == OK


def test_overspeed_shuts_down():
    m = Monitor()
    limp, _ = run(m, 5, rpm=9000.0)
    assert limp == SHUTDOWN and m.fault == F_OVERSPEED


def test_overboost_shuts_down():
    m = Monitor()
    limp, _ = run(m, 5, map_kpa=300.0)
    assert limp == SHUTDOWN and m.fault == F_OVERBOOST


def test_a_limp_does_not_clear_itself():
    """An intermittent fault that clears its own limp is an engine that
    keeps trying. It stays until the key is cycled."""
    m = Monitor()
    run(m, 30, pedal_a=80.0, pedal_b=10.0)
    assert m.limp >= REDUCED
    run(m, 200)
    assert m.limp >= REDUCED
    m.reset()
    assert m.limp == OK


def test_the_root_cause_is_kept_not_the_last_symptom():
    m = Monitor()
    run(m, 100, pedal_a=80.0, pedal_b=10.0, torque=390.0)
    assert m.fault == F_PEDAL_PLAUSIBILITY
    assert F_TORQUE_EXCEEDS_PERMISSIBLE in m.faults


@pytest.mark.parametrize("limp,cap", [(OK, 400.0), (REDUCED, 200.0),
                                      (IDLE_ONLY, 30.0), (SHUTDOWN, 0.0)])
def test_torque_cap_per_limp_level(limp, cap):
    m = Monitor()
    m.limp = limp
    assert m.torque_cap(400.0) == cap


# ---- the engine obeys the limits ------------------------------------------
def test_overboost_cuts_fuel(sim):
    sim.pedal = 1.0
    sim.tune.engine["boost_max_kpa"] = 400.0       # let the target run away
    sim.tune.engine["overboost_cut_kpa"] = 150.0   # but cut early
    for _ in range(600):
        sim._step()
    ch = sim.channels()
    assert ch["map"] < 200.0, "boost ran past the cut with no intervention"
    assert ch["limp_level"] >= 1


def test_boost_target_is_clamped_to_the_hardware_limit(sim):
    sim.tune.tables["boost"].values[:] = 40.0      # ask for 40 psi
    sim.tune.engine["boost_max_kpa"] = 180.0
    sim.pedal = 1.0
    for _ in range(400):
        sim._step()
    assert sim.channels()["map"] < 200.0


def test_a_downshift_that_would_overrev_is_refused(sim):
    sim.pedal = 1.0
    for _ in range(1200):
        sim._step()
    sim.pedal = 0.0
    top = sim.gear
    assert top >= 2, "the car never got out of first"
    sim.gear = top
    sim.v = 80.0                                   # 288 km/h worth of wheel speed
    sim.request_shift(up=False)
    assert sim.shift is None
    assert sim.shift_inhibit == 1.0


def test_a_normal_downshift_is_allowed(sim):
    sim.v = 15.0
    sim.gear = 4
    for _ in range(20):
        sim._step()
    sim.request_shift(up=False)
    assert sim.shift is not None


# ---- the coordinator is untrusted code ------------------------------------
class Raising:
    def start_shift(self, *a, **k):
        pass

    def update(self, *a, **k):
        raise RuntimeError("a bug in the exercise")


class Absurd:
    def start_shift(self, *a, **k):
        pass

    def update(self, state, dt, driver_torque, mbt):
        return -500.0, driver_torque, driver_torque


class NotFinite:
    def start_shift(self, *a, **k):
        pass

    def update(self, state, dt, driver_torque, mbt):
        return float("nan"), driver_torque, driver_torque


def test_a_coordinator_exception_does_not_stop_the_engine(sim):
    sim.coord, sim.coord_state = Raising(), {}
    sim.pedal = 0.8
    for _ in range(100):
        sim._step()
    ch = sim.channels()
    assert sim.step_error is None, "the simulation died"
    assert ch["rpm"] > 500.0
    assert ch["coord_fault"] == 1.0
    assert "a bug in the exercise" in (sim.coord_error or "")


def test_a_coordinator_exception_is_reported_once_not_every_tick(sim):
    sim.coord, sim.coord_state = Raising(), {}
    sim.pedal = 0.5
    for _ in range(100):
        sim._step()
    assert sim.coord is None, "the broken coordinator is still being called"


@pytest.mark.parametrize("coord", [Absurd(), NotFinite()])
def test_coordinator_retard_is_clamped(sim, coord):
    sim.coord, sim.coord_state = coord, {"phase": "cutting"}
    sim.pedal = 0.8
    for _ in range(30):
        sim._step()
    sim.request_shift(True)
    for _ in range(30):
        sim._step()
    ch = sim.channels()
    max_cut = sim.tune.engine["max_cut_retard"]
    assert math.isfinite(ch["spark"])
    assert ch["cut_deg"] <= max_cut + 1e-6


def test_a_coordinator_cannot_wedge_the_air_path(sim):
    """An unfinished coordinator that never leaves its cut state must not
    be able to hold the throttle shut forever."""
    class NeverFinishes:
        def start_shift(self, *a, **k):
            pass

        def update(self, state, dt, driver_torque, mbt):
            return mbt - 30.0, driver_torque * 0.2, driver_torque * 0.2

    sim.coord, sim.coord_state = NeverFinishes(), {"phase": "cutting"}
    sim.pedal = 1.0
    for _ in range(50):
        sim._step()
    sim.request_shift(True)
    for _ in range(500):
        sim._step()
    assert sim.shift is None, "the shift never ended"
    assert sim.channels()["cut_deg"] < 1.0, "spark is still cut after the shift"


# ---- the monitor must not punish ordinary driving -------------------------
def test_lifting_off_does_not_limp_the_car(sim):
    """A pedal lift is instant; the manifold emptying is not. The engine
    keeps making torque for a few hundred milliseconds after the driver
    backs off, and a monitor that expects torque to vanish with the pedal
    limps the car every single time."""
    sim.pedal = 0.9
    for _ in range(700):
        sim._step()
    sim.pedal = 0.1
    for _ in range(300):
        sim._step()
    ch = sim.channels()
    assert ch["limp_level"] == 0, (
        f"limped on a throttle lift: fault {ch['fault_code']:.0f}, "
        f"torque {ch['torque']:.0f} vs permissible {ch['torque_permissible']:.0f}")


def test_a_long_mixed_drive_never_limps(sim):
    for i in range(4000):
        sim.pedal = 0.9 if (i // 700) % 2 == 0 else 0.1
        sim._step()
    assert sim.monitor.limp == 0, f"limped during normal driving: {sim.monitor.faults}"
    assert sim.step_error is None


def test_sustained_unrequested_torque_is_still_caught():
    """The lag must not make the monitor blind. Torque that stays up
    with the pedal down is still a fault, just a little later."""
    m = Monitor()
    limp = OK
    for _ in range(300):
        limp, _ = m.update(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 390.0, 3000.0,
                           400.0, 7200.0, 150.0, 265.0)
    assert limp >= IDLE_ONLY
    assert m.fault == F_TORQUE_EXCEEDS_PERMISSIBLE


def test_an_automatic_downshift_is_guarded_too(sim):
    """The guard was only on the manual path. An automatic downshift can
    put the engine past its limit just as easily."""
    sim.v = 90.0
    sim.gear = 2
    sim.pedal = 0.0
    sim.request_shift(False)
    assert sim.shift is None
    assert sim.shift_inhibit == 1.0


def test_the_inhibit_marker_does_not_latch_forever(sim):
    sim.v = 90.0
    sim.gear = 2
    sim.request_shift(False)
    assert sim.shift_inhibit == 1.0
    sim.v = 12.0
    sim.request_shift(False)
    assert sim.shift is not None
    assert sim.shift_inhibit == 0.0


# ---- direct injection behaviour ------------------------------------------
def test_rail_pressure_follows_its_target(sim):
    sim.pedal = 0.5
    for _ in range(900):
        sim._step()
    ch = sim.channels()
    assert abs(ch["rail_error"]) < 500.0, (
        f"rail {ch['rail_kpa']:.0f} against target {ch['rail_target']:.0f}")
    assert 0.0 < ch["hpfp_duty"] < 100.0


def test_an_undersized_pump_droops_the_rail(sim, tune):
    """The failure that is invisible unless the rail is modelled: the
    injectors outrun the pump, every pulse delivers less than planned,
    and the engine leans out at full load."""
    from tuner.core.sim_ecu import SimulatedECU

    weak = tune
    weak.engine["hpfp_capacity_g_s"] = 6.0
    s = SimulatedECU(weak)
    s.connect_ecu()
    s.pedal = 1.0
    for _ in range(900):
        s._step()
    ch = s.channels()
    s.disconnect_ecu()
    assert ch["rail_error"] < -2000.0, "an undersized pump held full pressure"
    assert ch["hpfp_duty"] >= 99.0, "the pump was not even at full duty"
    assert ch["pw_ms"] > 2.0, "pulse width did not compensate for the droop"


def test_pulse_width_compensates_for_rail_pressure(sim):
    """Flow goes as the square root of the pressure drop, so a rail that
    has drooped needs a longer pulse for the same fuel. An ECU that uses
    a nominal rail pressure instead of the measured one runs lean here."""
    sim.pedal = 0.6
    for _ in range(600):
        sim._step()
    strong = sim.channels()["pw_ms"]
    sim.tune.engine["hpfp_capacity_g_s"] = 5.0
    for _ in range(600):
        sim._step()
    weak = sim.channels()
    assert weak["pw_ms"] > strong, (
        f"pulse width {weak['pw_ms']:.2f} did not rise as the rail fell to "
        f"{weak['rail_kpa']:.0f}")


def test_a_split_injection_is_commanded_at_high_load(sim):
    sim.pedal = 1.0
    for _ in range(900):
        sim._step()
    ch = sim.channels()
    assert ch["inj_pulses"] == 2, "no pilot pulse at full load"
    assert 0.0 < ch["inj_split"] <= 0.6


def test_a_single_pulse_at_light_load(sim):
    sim.pedal = 0.12
    for _ in range(600):
        sim._step()
    assert sim.channels()["inj_pulses"] == 1


def test_injector_duty_is_measured_against_the_usable_window(sim):
    """Against the whole cycle a direct injector looks about three times
    larger than it is, and the first sign of that error on a real engine
    is a lean misfire at full load."""
    sim.pedal = 1.0
    for _ in range(900):
        sim._step()
    ch = sim.channels()
    window_ms = (sim.tune.engine["inj_window_deg"] / 360.0
                 * 60000.0 / max(ch["rpm"], 100.0))
    assert ch["inj_duty"] == pytest.approx(ch["pw_ms"] / window_ms * 100.0, rel=0.02)
    assert ch["inj_duty"] > 15.0, "duty is implausibly low for full load"
