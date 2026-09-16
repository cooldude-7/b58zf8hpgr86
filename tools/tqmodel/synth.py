"""Synthetic log generator.

Phase 0 has not happened yet, so there are no real DME logs. This produces
plausible stand-in data with a KNOWN ground truth, so the whole pipeline is
runnable today and the validation plots can be checked against an answer
you already know.

Replace with real logs when they exist -- nothing downstream changes.
"""
import numpy as np
from .model import Engine, air_mass, brake_torque, spark_efficiency


def truth_ve(rpm, map_kpa):
    """A plausible turbo VE surface: peaks mid-range, falls off at both ends,
    exceeds 1.0 on boost where scavenging helps."""
    r = (np.asarray(rpm) - 4200.0) / 2600.0
    m = np.clip(np.asarray(map_kpa) / 100.0, 0.2, 2.6)
    return np.clip(0.88 + 0.16 * np.exp(-r ** 2) + 0.07 * (m - 1.0), 0.35, 1.15)


def truth_mbt(rpm, map_kpa):
    """MBT rises with RPM, falls with load. Knock limiting is applied
    separately in generate() -- this is the unconstrained optimum."""
    return (12.0 + 0.0026 * np.asarray(rpm)
            - 0.055 * np.clip(np.asarray(map_kpa) - 100.0, 0.0, None))


def generate(n=6000, seed=7, eng: Engine = None, injector_flow_error=0.0):
    """Generate a synthetic drive log.

    injector_flow_error: fractional error in the assumed injector flow rate
    used later when back-calculating VE. 0.07 means the calibration thinks
    the injectors flow 7% more than they do -- the classic error that hides
    inside a VE table and corrupts a torque model.
    """
    eng = eng or Engine()
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 0.01

    rpm = np.clip(3900 + 2500 * np.sin(t / 7.0) + 1300 * np.sin(t / 2.3)
                  + rng.normal(0, 40, n), 900, 7200)
    map_kpa = np.clip(55 + 105 * (0.5 + 0.5 * np.sin(t / 5.0 + 1.1))
                      + 25 * np.sin(t / 1.7) + rng.normal(0, 2.0, n), 25, 240)
    t_charge = 305 + 0.16 * np.clip(map_kpa - 100, 0, None) + rng.normal(0, 1.5, n)

    ve = truth_ve(rpm, map_kpa)
    mbt = truth_mbt(rpm, map_kpa)

    # knock limit bites at high load, hardest at low rpm where the end gas
    # has the most real time to cook before the flame arrives
    knock_limit = (24.0 - 0.28 * np.clip(map_kpa - 95.0, 0, None)
                   + 0.0020 * rpm)
    spark = np.minimum(mbt, knock_limit)

    lam = np.where(map_kpa > 140, 0.85, 1.0) + rng.normal(0, 0.006, n)

    air_true = air_mass(ve, map_kpa, t_charge, eng)
    torque = brake_torque(ve, map_kpa, t_charge, rpm, spark, mbt, lam, eng)
    torque_ref = torque + rng.normal(0, 1.8, n)   # stands in for DME broadcast

    # injector data used by the log consumer, optionally wrong
    flow_true = 0.0105                             # g/ms
    deadtime = 0.9
    fuel_g = air_true / eng.afr_stoich / lam
    pw = fuel_g / flow_true + deadtime

    return dict(
        time_s=t, rpm=rpm, map_kpa=map_kpa, t_charge_k=t_charge,
        spark=spark, mbt=mbt, lam=lam,
        pulse_width_ms=pw, deadtime_ms=deadtime,
        assumed_flow_g_per_ms=flow_true * (1.0 + injector_flow_error),
        torque_ref=torque_ref,
        ve_true=ve, air_true=air_true,
    )
