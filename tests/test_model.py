"""The torque model: the golden reference the firmware will be checked against.

Every number here is either a physical identity (an inverse that must round
trip) or a documented anchor. If one of these moves, the firmware port and
every tune built on the model move with it, so they are asserted tightly.
"""
import numpy as np
import pytest

from tqmodel.model import (Engine, air_mass, authority, base_torque,
                           brake_torque, friction_torque, indicated_efficiency,
                           lambda_efficiency, required_air, spark_efficiency,
                           ve_from_air)
from tqmodel.units import (boost_psi_to_kpa_abs, kpa_abs_to_boost_psi,
                           lbft_to_nm, nm_to_lbft)

ENG = Engine()


# ---- air ------------------------------------------------------------------
def test_air_mass_scales_with_pressure():
    a1 = float(air_mass(1.0, 100.0, 300.0, ENG))
    a2 = float(air_mass(1.0, 200.0, 300.0, ENG))
    assert a2 == pytest.approx(2 * a1, rel=1e-12)


def test_air_mass_falls_with_temperature():
    hot = float(air_mass(1.0, 100.0, 400.0, ENG))
    cold = float(air_mass(1.0, 100.0, 300.0, ENG))
    assert hot < cold
    assert hot == pytest.approx(cold * 300.0 / 400.0, rel=1e-12)


def test_air_mass_magnitude_is_physical():
    # 500 cc cylinder, 100 kPa, 300 K, VE 1.0 -> about 0.58 g of air
    a = float(air_mass(1.0, 100.0, 300.0, ENG))
    assert 0.55 < a < 0.62


@pytest.mark.parametrize("ve", [0.3, 0.85, 1.0, 1.25])
@pytest.mark.parametrize("map_kpa", [30.0, 100.0, 240.0])
def test_ve_air_round_trip(ve, map_kpa):
    a = air_mass(ve, map_kpa, 320.0, ENG)
    assert float(ve_from_air(a, map_kpa, 320.0, ENG)) == pytest.approx(ve, abs=1e-12)


# ---- spark ----------------------------------------------------------------
def test_spark_efficiency_is_one_at_mbt():
    assert float(spark_efficiency(0.0)) == 1.0


def test_spark_efficiency_has_zero_slope_at_mbt():
    """MBT is the maximum by definition. A curve with a linear term says
    the first half degree already costs torque, which would mean the
    reference point is not the maximum."""
    slope = (float(spark_efficiency(1e-3)) - 1.0) / 1e-3
    assert abs(slope) < 1e-4


@pytest.mark.parametrize("deg,expected", [(10, 0.93), (20, 0.76), (30, 0.50)])
def test_spark_efficiency_anchors(deg, expected):
    assert float(spark_efficiency(deg)) == pytest.approx(expected, abs=0.01)


def test_spark_efficiency_is_monotonic_and_bounded():
    d = np.linspace(0, 60, 200)
    e = spark_efficiency(d)
    assert np.all(np.diff(e) <= 1e-12)
    assert e.min() >= 0.0 and e.max() <= 1.0


def test_spark_efficiency_ignores_advance_past_mbt():
    # advancing past MBT is handled by the caller (it knocks); the curve
    # itself is defined on retard only and must not return more than 1
    assert float(spark_efficiency(-10.0)) == 1.0


def test_coordinator_shares_the_same_curve():
    """The shift coordinator carries its own plain-arithmetic copy so it can
    run without numpy. The two must not drift apart."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from shift.coordinator import fraction_for_retard, retard_for_fraction
    for d in range(0, 36):
        assert fraction_for_retard(d) == pytest.approx(float(spark_efficiency(d)), abs=1e-9)
    for f in (0.95, 0.8, 0.6, 0.5):
        assert fraction_for_retard(retard_for_fraction(f)) == pytest.approx(f, abs=1e-9)


# ---- lambda ---------------------------------------------------------------
def test_lambda_efficiency_peaks_rich_of_stoich():
    lam = np.linspace(0.7, 1.2, 501)
    assert lam[int(np.argmax(lambda_efficiency(lam)))] == pytest.approx(0.88, abs=0.01)


def test_lambda_efficiency_is_one_at_peak():
    assert float(lambda_efficiency(0.88)) == pytest.approx(1.0, abs=1e-12)


def test_lambda_efficiency_never_negative():
    assert float(lambda_efficiency(3.0)) >= 0.0


# ---- torque ---------------------------------------------------------------
def test_base_torque_rises_with_air():
    assert float(base_torque(0.8, 4000, ENG)) > float(base_torque(0.4, 4000, ENG))


def test_base_torque_is_roughly_linear_in_air():
    """Indicated torque comes from fuel energy, and fuel tracks air, so
    doubling the charge should roughly double it."""
    t1 = float(base_torque(0.4, 4000, ENG))
    t2 = float(base_torque(0.8, 4000, ENG))
    assert t2 == pytest.approx(2 * t1, rel=0.02)


def test_friction_rises_with_rpm():
    assert float(friction_torque(6000, 100, ENG)) > float(friction_torque(1000, 100, ENG))


def test_brake_torque_is_less_than_indicated():
    kw = dict(ve=0.95, map_kpa=150.0, t_charge_k=320.0, rpm=4000,
              spark=18.0, mbt=18.0, lam=0.88, eng=ENG)
    air = float(air_mass(kw["ve"], kw["map_kpa"], kw["t_charge_k"], ENG))
    assert float(brake_torque(**kw)) < float(base_torque(air, 4000, ENG))


def test_retarding_spark_costs_torque():
    kw = dict(ve=0.95, map_kpa=150.0, t_charge_k=320.0, rpm=4000,
              mbt=20.0, lam=0.88, eng=ENG)
    assert float(brake_torque(spark=20.0, **kw)) > float(brake_torque(spark=5.0, **kw))


# ---- the inverse model ----------------------------------------------------
@pytest.mark.parametrize("rpm", [1500, 3000, 5500])
@pytest.mark.parametrize("target", [80.0, 200.0, 320.0])
def test_required_air_inverts_brake_torque(rpm, target):
    """The whole torque structure rests on this: ask for a torque, get the
    air that produces it, and the forward model must agree."""
    air = float(required_air(target, rpm, planned_spark=18.0, mbt=18.0,
                             lam=0.88, map_kpa=150.0, eng=ENG))
    made = float(base_torque(air, rpm, ENG)) \
        * float(spark_efficiency(0.0)) * float(lambda_efficiency(0.88)) \
        - float(friction_torque(rpm, 150.0, ENG))
    assert made == pytest.approx(target, rel=1e-6)


def test_authority_is_non_negative():
    a = float(authority(ve=0.9, map_kpa=140.0, t_charge_k=320.0, rpm=4000,
                        spark=18.0, mbt=18.0, lam=0.88, eng=ENG))
    assert a >= 0.0


def test_authority_shrinks_when_spark_is_already_retarded():
    kw = dict(ve=0.9, map_kpa=140.0, t_charge_k=320.0, rpm=4000,
              mbt=25.0, lam=0.88, eng=ENG)
    assert float(authority(spark=25.0, **kw)) > float(authority(spark=5.0, **kw))


def test_indicated_efficiency_is_plausible():
    assert 0.30 < indicated_efficiency(ENG) < 0.45


# ---- units ----------------------------------------------------------------
def test_boost_round_trip():
    for psi in (-5.0, 0.0, 7.3, 22.0):
        assert kpa_abs_to_boost_psi(boost_psi_to_kpa_abs(psi)) == pytest.approx(psi, abs=1e-9)


def test_atmospheric_is_zero_boost():
    assert kpa_abs_to_boost_psi(101.325) == pytest.approx(0.0, abs=1e-3)


def test_torque_unit_round_trip():
    assert nm_to_lbft(lbft_to_nm(100.0)) == pytest.approx(100.0, abs=1e-9)
