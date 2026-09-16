"""Torque model analysis toolkit.

Offline reference implementation of the torque model described in
docs/torque-model.md. Validate here -- with plots, a debugger and no flash
cycle -- before porting anything to firmware.

This also serves as the golden reference for testing the C implementation:
run the same vectors through both and compare.
"""
from . import model, ve, dynamics, plots, units, synth  # noqa: F401
