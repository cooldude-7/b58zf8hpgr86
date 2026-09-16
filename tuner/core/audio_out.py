"""Real-time audio output for the engine synth.

A sounddevice output stream pulls blocks from EngineSynth in the audio
thread. The GUI thread only writes a small target-state dict; the callback
eases the synth toward it so 25 Hz channel updates do not zipper.

If sounddevice or an output device is missing, the object reports itself
unavailable and everything else in the app carries on without sound.
"""
import threading

import numpy as np

from .engine_sound import SR, EngineSynth

try:
    import sounddevice as sd
    _ERR = None
except Exception as e:                      # noqa: BLE001 -- missing wheel, missing PortAudio
    sd, _ERR = None, str(e)

BLOCK = 512


class AudioOutput:
    def __init__(self):
        self.synth = EngineSynth()
        self.target = dict(rpm=0.0, load=0.0, boost=0.0, throttle=0.0, cut=0.0, limiter=False)
        self.state = dict(self.target)
        self.volume = 0.6
        self.stand_in_cut = True            # bang on every shift until the coordinator cuts spark
        self._lock = threading.Lock()
        self._stream = None
        self.error = _ERR

    @property
    def available(self) -> bool:
        return sd is not None

    def start(self):
        if self._stream or sd is None:
            return
        try:
            self._stream = sd.OutputStream(samplerate=SR, channels=1, blocksize=BLOCK,
                                           dtype="float32", callback=self._callback)
            self._stream.start(); self.error = None
        except Exception as e:              # noqa: BLE001 -- no device, device busy
            self._stream, self.error = None, str(e)

    def stop(self):
        if self._stream:
            try: self._stream.stop(); self._stream.close()
            except Exception: pass
            self._stream = None

    def update(self, ch: dict):
        cut = min(ch.get("cut_deg", 0.0) / 20.0, 1.0)
        if self.stand_in_cut and ch.get("shift_phase", 0) in (2, 3):
            cut = max(cut, 1.0)
        with self._lock:
            self.target.update(rpm=ch.get("rpm", 0.0), load=min(ch.get("map", 30.0) / 200.0, 1.0),
                               boost=ch.get("boost", 0.0), throttle=ch.get("tps", 0.0) / 100.0,
                               cut=cut, limiter=bool(ch.get("overrun", 0)) and False)

    def _callback(self, out, frames, time_info, status):
        with self._lock:
            t = dict(self.target)
        s = self.state
        for k in ("rpm", "load", "boost", "throttle"):
            s[k] += (t[k] - s[k]) * 0.35             # ease over a few blocks
        s["cut"] = t["cut"]                          # the cut must be instant
        block = self.synth.render(frames, s["rpm"], s["load"], s["boost"], s["throttle"], s["cut"], t["limiter"])
        out[:, 0] = np.clip(block * self.volume, -1.0, 1.0)
