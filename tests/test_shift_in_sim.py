"""Does a torque cut actually reach the engine, and does it do any good?

The shift coordinator in tools/shift is an exercise with its TODOs left
open on purpose, so these tests inject their own small reference
coordinator. That keeps the exercise unsolved while still proving the
plumbing between a coordinator and the engine works in both directions.
"""
import pytest

from tqmodel.model import spark_efficiency


class Reference:
    """A minimal correct coordinator: cut on the fast path, hold the air
    request where it was, ramp back to base when the shift is done."""

    HOLD_S = 0.20
    RAMP_S = 0.15

    def __init__(self, chase_air_bug=False):
        self.chase_air_bug = chase_air_bug

    def new_controller(self):
        return {"phase": "idle", "t": 0.0, "target": 0.0, "entry": 0.0}

    def start_shift(self, state, target_torque, current_torque):
        state["phase"] = "cutting"
        state["t"] = 0.0
        state["target"] = target_torque
        state["entry"] = current_torque

    def update(self, state, dt, driver_torque, spark_now):
        phase = state.get("phase", "idle")
        if phase == "idle":
            return spark_now, driver_torque, driver_torque
        state["t"] += dt
        entry = max(state.get("entry", driver_torque), 1.0)
        want = max(state.get("target", 0.0), 0.0)
        frac = min(max(want / entry, 0.05), 1.0)
        # degrees of retard that produce this fraction of the torque
        deg = ((1.0 - frac) / 1.096e-3) ** (1.0 / 1.8)
        if state["t"] < self.HOLD_S:
            spark = spark_now - deg
            torque = want
        elif state["t"] < self.HOLD_S + self.RAMP_S:
            k = (state["t"] - self.HOLD_S) / self.RAMP_S
            spark = spark_now - deg * (1.0 - k)
            torque = want + (driver_torque - want) * k
        else:
            state["phase"] = "idle"
            return spark_now, driver_torque, driver_torque
        # The air request is the whole lesson. Holding it at the driver's
        # request keeps the manifold full so torque returns instantly after
        # the shift. Chasing the cut with air is the classic bug.
        air = driver_torque / frac if self.chase_air_bug else driver_torque
        return spark, air, torque


def wot(sim, steps):
    for _ in range(steps):
        sim._step()


def test_the_cut_reaches_the_engine(sim):
    """The plumbing test: a coordinator asking for retard must actually
    move the spark the engine runs on."""
    sim.coord = Reference()
    sim.coord_state = sim.coord.new_controller()
    sim.pedal = 1.0
    wot(sim, 300)
    sim.request_shift(True)
    cut_seen, torque_during = 0.0, []
    for _ in range(25):
        sim._step()
        ch = sim.channels()
        cut_seen = max(cut_seen, ch["cut_deg"])
        torque_during.append(ch["torque"])
    assert cut_seen > 8.0, f"spark was barely cut ({cut_seen:.1f} deg)"
    assert min(torque_during) < 0.8 * max(torque_during)


def test_the_cut_is_bounded_by_the_engine_scalar(sim):
    sim.coord = Reference()
    sim.coord_state = sim.coord.new_controller()
    sim.pedal = 1.0
    wot(sim, 300)
    sim.request_shift(True)
    peak = 0.0
    for _ in range(40):
        sim._step()
        peak = max(peak, sim.channels()["cut_deg"])
    assert peak <= sim.tune.engine["max_cut_retard"] + 1e-6


def test_spark_returns_to_base_after_the_shift(sim):
    sim.coord = Reference()
    sim.coord_state = sim.coord.new_controller()
    sim.pedal = 1.0
    wot(sim, 300)
    sim.request_shift(True)
    wot(sim, 120)
    assert sim.shift is None
    assert sim.channels()["cut_deg"] < 1.0


def test_chasing_the_cut_with_air_overshoots_afterwards(tune):
    """The failure the exercise exists to teach. Holding the air request
    keeps the manifold where it was; chasing the cut inflates it, and the
    torque that lands on the clutch when spark returns is the overshoot.

    Measured across several engines rather than one, because it is a
    population effect and not a law. On a randomly generated plant it
    holds roughly five times in six; the sixth engine genuinely does not
    overshoot, because how much the manifold can inflate during the cut
    depends on that engine's VE surface and knock limit. Asserting it on
    ONE unseeded engine is a test that fails about one run in six, on
    somebody else's machine, for a reason that looks like nothing.
    """
    from tuner.core.sim_ecu import SimulatedECU

    def peak_after_shift(chase, seed):
        s = SimulatedECU(tune, seed=seed)
        s.connect_ecu()
        s.coord = Reference(chase_air_bug=chase)
        s.coord_state = s.coord.new_controller()
        s.pedal = 1.0
        wot(s, 300)
        before = s.channels()["torque"]
        s.request_shift(True)
        wot(s, 45)
        peak = max(s.channels()["torque"] for _ in [s._step() for _ in range(40)])
        s.disconnect_ecu()
        return before, peak

    seeds = (11, 22, 33, 44, 55, 66, 77)
    deltas = [peak_after_shift(True, s)[1] - peak_after_shift(False, s)[1]
              for s in seeds]
    overshot = sum(1 for d in deltas if d > 0)
    mean = sum(deltas) / len(deltas)

    assert overshot >= len(seeds) - 2, (
        f"chasing air overshot on only {overshot} of {len(seeds)} engines: "
        f"{[round(d, 1) for d in deltas]}"
    )
    assert mean > 2.0, (
        f"mean overshoot {mean:.1f} Nm is too small to be the lesson this "
        f"lab teaches"
    )


def test_a_coordinator_that_does_nothing_leaves_a_harsh_shift(sim):
    """The control case: with no cut at all the engine keeps making full
    torque through the shift, which is what the clutch has to absorb."""
    class Passive:
        def start_shift(self, *a, **k):
            pass

        def update(self, state, dt, driver_torque, spark_now):
            return spark_now, driver_torque, driver_torque

    sim.coord, sim.coord_state = Passive(), {}
    sim.pedal = 1.0
    wot(sim, 300)
    sim.request_shift(True)
    cut = 0.0
    for _ in range(25):
        sim._step()
        cut = max(cut, sim.channels()["cut_deg"])
    assert cut < 1.0


def test_the_reference_coordinator_matches_the_shared_spark_curve():
    r = Reference()
    st = r.new_controller()
    r.start_shift(st, 100.0, 400.0)
    spark, _air, _t = r.update(st, 0.01, 400.0, 20.0)
    deg = 20.0 - spark
    assert float(spark_efficiency(deg)) == pytest.approx(0.25, abs=0.01)
