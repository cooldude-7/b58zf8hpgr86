"""Forward and inverse torque model.

Conventions, fixed here and used everywhere:
  - spark advance in degrees BTDC, positive = advanced
  - air mass in grams per cylinder per cycle
  - torque in Nm, pressure in kPa absolute, temperature in K
  - lambda, not AFR
"""
from dataclasses import dataclass, field
import numpy as np

R_AIR = 0.287  # kJ/(kg*K)


@dataclass
class Engine:
    n_cyl: int = 4
    displacement_l: float = 2.0
    compression_ratio: float = 11.0
    afr_stoich: float = 14.7
    # Chen-Flynn friction coefficients (FMEP, bar)
    cf_a: float = 0.4
    cf_b: float = 0.005
    cf_c: float = 0.09
    cf_d: float = 0.0009
    stroke_m: float = 0.094

    @property
    def vd_per_cyl_l(self) -> float:
        return self.displacement_l / self.n_cyl


def air_mass(ve, map_kpa, t_charge_k, eng: Engine):
    """Charge mass per cylinder per cycle, in grams. Steady-state form.

    Transients need the manifold filling model in dynamics.py -- this
    equation assumes the manifold is in equilibrium and will under- or
    over-read during tip-in.
    """
    rho = np.asarray(map_kpa) / (R_AIR * np.asarray(t_charge_k))  # kg/m^3
    return np.asarray(ve) * eng.vd_per_cyl_l * 1e-3 * rho * 1000.0


def ve_from_air(air_g, map_kpa, t_charge_k, eng: Engine):
    """Inverse of air_mass -- the VE implied by a measured charge mass."""
    rho = np.asarray(map_kpa) / (R_AIR * np.asarray(t_charge_k))
    return np.asarray(air_g) / (eng.vd_per_cyl_l * 1e-3 * rho * 1000.0)


def spark_efficiency(delta_from_mbt_deg):
    """Torque as a fraction of MBT torque, vs degrees retarded from MBT.

    Near-universal curve -- ship this as a default and verify it on a dyno
    rather than authoring it per engine. Flat on top (a few degrees costs
    almost nothing), falling away steeply past ~15 degrees.
    """
    d = np.clip(np.asarray(delta_from_mbt_deg, dtype=float), 0.0, 60.0)
    # fitted to the usual anchors: 10 deg -> ~0.91, 20 -> ~0.73, 30 -> ~0.50
    return np.clip(1.0 - 6.667e-3 * d - 3.333e-4 * d ** 2, 0.0, 1.0)


def lambda_efficiency(lam):
    """Torque vs lambda, normalised to 1.0 at best-torque lambda (~0.88).

    Also near-universal. Peaks slightly rich of stoichiometric.
    """
    lam = np.asarray(lam, dtype=float)
    return np.clip(1.0 - 1.15 * (lam - 0.88) ** 2, 0.0, 1.0)


def indicated_efficiency(eng: Engine, realism=0.62):
    """Indicated thermal efficiency.

    Ideal Otto (1 - CR^-(gamma-1)) scaled by a realism factor for heat loss,
    finite burn duration and incomplete combustion. Real engines reach
    roughly 60-65% of the ideal cycle. Replace with a measured base torque
    map once dyno data exists.
    """
    ideal = 1.0 - eng.compression_ratio ** -0.4
    return ideal * realism


def base_torque(air_g, rpm, eng: Engine):
    """Indicated torque at MBT and best-torque lambda, in Nm.

    Anchored on combustion thermodynamics: a gram of air carries a fixed
    amount of fuel energy, and thermal efficiency converts it to work.
    Replace this with a measured map once dyno data exists -- the map
    absorbs efficiency variation this closed form cannot.
    """
    air_g = np.asarray(air_g, dtype=float)
    fuel_g = air_g / eng.afr_stoich
    energy_j = fuel_g * 1e-3 * 44.0e6          # LHV ~44 MJ/kg
    work_j = energy_j * indicated_efficiency(eng) * eng.n_cyl
    return work_j / (4.0 * np.pi)               # 4-stroke: 2 revolutions


def friction_torque(rpm, map_kpa, eng: Engine):
    """Chen-Flynn FMEP correlation, converted to Nm.

    Four fitted coefficients, not a map. Fit them warm and remember that a
    cold engine has substantially higher friction than these describe.
    """
    rpm = np.asarray(rpm, dtype=float)
    sp = 2.0 * eng.stroke_m * rpm / 60.0        # mean piston speed, m/s
    pmax = np.asarray(map_kpa, dtype=float) * eng.compression_ratio / 100.0
    fmep_bar = eng.cf_a + eng.cf_b * pmax + eng.cf_c * sp + eng.cf_d * sp ** 2
    return fmep_bar * 1e5 * eng.displacement_l * 1e-3 / (4.0 * np.pi)


def brake_torque(ve, map_kpa, t_charge_k, rpm, spark, mbt, lam, eng: Engine,
                 accessory_nm=0.0):
    """Full forward model: conditions in, crank torque out.

    Returns torque net of accessory load -- this is the number the
    transmission wants, not indicated and not brake.
    """
    air = air_mass(ve, map_kpa, t_charge_k, eng)
    t_ind = (base_torque(air, rpm, eng)
             * spark_efficiency(np.asarray(mbt) - np.asarray(spark))
             * lambda_efficiency(lam))
    return t_ind - friction_torque(rpm, map_kpa, eng) - accessory_nm


def required_air(torque_target, rpm, planned_spark, mbt, lam, map_kpa,
                 eng: Engine, accessory_nm=0.0):
    """Inverse model: torque target in, required charge mass out.

    Note the divisor uses the spark the controller PLANS to run. Retarded
    plans demand more air for the same torque -- which is where torque
    reserve comes from, and why a shift cut must be excluded from this
    calculation (see the air-chase failure in docs/torque-model.md).
    """
    t_ind_needed = (np.asarray(torque_target)
                    + friction_torque(rpm, map_kpa, eng) + accessory_nm)
    eff = (spark_efficiency(np.asarray(mbt) - np.asarray(planned_spark))
           * lambda_efficiency(lam))
    t_at_mbt = t_ind_needed / np.maximum(eff, 1e-6)

    # invert base_torque analytically
    work_j = t_at_mbt * 4.0 * np.pi
    energy_j = work_j / (indicated_efficiency(eng) * eng.n_cyl)
    return energy_j / 44.0e6 * 1e3 * eng.afr_stoich


def authority(ve, map_kpa, t_charge_k, rpm, spark, mbt, lam, eng: Engine,
              max_retard_deg=30.0, accessory_nm=0.0):
    """Fast-path torque authority: how much can be removed on the next event.

    This is the signal a two-box ECU/TCU setup structurally cannot provide,
    and the reason the transmission can plan a pressure trajectory instead
    of hoping.
    """
    now = brake_torque(ve, map_kpa, t_charge_k, rpm, spark, mbt, lam, eng,
                       accessory_nm)
    floor_spark = np.asarray(mbt) - max_retard_deg
    floor = brake_torque(ve, map_kpa, t_charge_k, rpm, floor_spark, mbt, lam,
                         eng, accessory_nm)
    return now - floor
