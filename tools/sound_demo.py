"""Render a synthesized run through the simulator to a WAV file.

    python tools/sound_demo.py out/engine_demo.wav

Idle, full-throttle launch through three shifts, then lift off. The cut
sound keys on the simulator's shift window so it is audible even before the
coordinator exercise is written; in the app it keys on the actual retard.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from tuner.core.tune import default_tune
from tuner.core.sim_ecu import SimulatedECU
from tuner.core.engine_sound import EngineSynth, SR, write_wav

sim = SimulatedECU(default_tune())
synth = EngineSynth()
BLOCK = 441                      # 10 ms of audio per physics step
chunks = []
timeline = [(1.5, 0.0), (9.0, 1.0), (4.0, 0.0)]     # seconds, pedal
for secs, pedal in timeline:
    sim.pedal = pedal
    for _ in range(int(secs / sim.dt)):
        sim._step(); ch = sim._channels
        # the coordinator exercise is placeholders, so the sim's shift window
        # stands in for the retard it would command; cut_deg is the real thing
        cut = max(min(ch["cut_deg"] / 20.0, 1.0), 1.0 if ch["shift_phase"] in (2, 3) else 0.0)
        limiter = ch["rpm"] > sim.tune.engine["rev_limit"]
        chunks.append(synth.render(BLOCK, ch["rpm"], min(ch["map"] / 200.0, 1.0), ch["boost"], ch["tps"] / 100.0, cut, limiter))
audio = np.concatenate(chunks)
audio *= 0.7 / max(np.abs(audio).max(), 1e-6)
out = sys.argv[1] if len(sys.argv) > 1 else "engine_demo.wav"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
write_wav(out, audio)
print(f"wrote {out}: {len(audio)/SR:.1f} s")
