"""Turn a scope or logic-analyser capture into a decoder configuration.

`decoder_config_b48()` ships four numbers that are admitted guesses, and
fw/README.md says they must come from a capture on the real engine. This
is what turns that session from a guessing game into a procedure.

What it CAN derive from crank and cam signals alone:

  * the crank wheel: tooth count, how many are missing, where the gap is
  * the cam wheels: how many features, and the spacings between them

What it CANNOT, and no amount of signal processing will change this:

  * ``gap_to_tdc_deg``, the angle from the gap to cylinder 1 compression
    TDC. That is a statement about where the pistons are, and the crank
    and cam sensors cannot see pistons.
  * which of the two crank revolutions is the compression stroke, unless
    something that fires once per cycle is captured alongside.

Both of those need one more measurement, and ``PROCEDURE.md`` says how to
get it. The tool asks for them rather than inventing them.
"""

from .capture import Capture, Channel, read_csv, edges_from_samples
from .fit import CamFit, WheelFit, fit_cam, fit_wheel
from .synth import synth_capture

__all__ = [
    "Capture", "Channel", "read_csv", "edges_from_samples",
    "WheelFit", "CamFit", "fit_wheel", "fit_cam", "synth_capture",
]
