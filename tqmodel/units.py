"""Unit conversions.

The model works in kPa ABSOLUTE throughout -- that is the convention fixed
in docs/torque-model.md and the math depends on it (the ideal gas law does
not accept gauge pressure).

Boost in psi is a DISPLAY unit. Convert at the plot, never in the model.
"""
ATM_KPA = 101.325
KPA_PER_PSI = 6.894757


def kpa_abs_to_boost_psi(map_kpa):
    """Absolute manifold pressure -> gauge boost in psi. Negative = vacuum."""
    return (map_kpa - ATM_KPA) / KPA_PER_PSI


def boost_psi_to_kpa_abs(psi):
    return psi * KPA_PER_PSI + ATM_KPA


def nm_to_lbft(nm):
    return nm * 0.7375621


def lbft_to_nm(lbft):
    return lbft / 0.7375621
