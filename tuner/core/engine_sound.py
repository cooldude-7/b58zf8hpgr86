"""Procedural engine sound, driven by live channels.

Not a recording of anything. A four-cylinder fires twice per revolution, so
each combustion event drops a short pulse into the output at rpm/30 Hz; the
pulse's own pitch is the exhaust resonance, which belongs to the pipe, not
the engine speed. Load crossfades a soft pulse into a harder, raspier one.
A turbo whistle tracks boost. A shift cut skips and retards pulses and adds
afterfire pops -- the mixture that was not burned in the cylinder lighting
in the exhaust.

Overlap-add of precomputed pulses: cheap enough for a real-time callback in
numpy with no per-sample Python. A sample bank of real recordings can
replace this behind the same render() interface.
"""
import numpy as np

SR = 44100


def _decay_sine(freq, seconds, tau, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return np.sin(2 * np.pi * freq * t) * np.exp(-t / tau)


def _noise_burst(seconds, tau, smooth, rng, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    n = rng.normal(0, 1, len(t)) * np.exp(-t / tau)
    k = np.ones(smooth) / smooth
    return np.convolve(n, k, mode="same")


class EngineSynth:
    def __init__(self, sr=SR, seed=3):
        self.sr = sr
        self.rng = np.random.default_rng(seed)
        r = self.rng
        # the pipe rings for longer than the gap between firings, so successive
        # pulses overlap into a continuous tone rather than separate bangs
        self.soft = (1.0 * _decay_sine(105, 0.090, 0.028) + 0.30 * _decay_sine(210, 0.090, 0.018)
                     + 0.08 * _noise_burst(0.090, 0.004, 24, r))
        self.hard = (1.0 * _decay_sine(105, 0.090, 0.030) + 0.55 * _decay_sine(315, 0.090, 0.014)
                     + 0.30 * _decay_sine(525, 0.090, 0.009) + 0.18 * _noise_burst(0.090, 0.006, 8, r))
        # afterfire pop: low, loud, long -- and rare
        self.pop = (2.2 * _decay_sine(70, 0.140, 0.040) + 1.0 * _noise_burst(0.140, 0.025, 12, r)
                    + 0.5 * _decay_sine(140, 0.140, 0.020))
        for name in ("soft", "hard", "pop"):
            a = getattr(self, name); setattr(self, name, (a / np.abs(a).max()).astype(np.float32))
        self.soft = np.pad(self.soft, (0, len(self.hard) - len(self.soft)))   # crossfade needs equal lengths
        self.tail = np.zeros(int(0.2 * sr), np.float32)
        self.phase = 0.0                 # firing events, in units of pulses
        self.turbo_phase = 0.0
        self.imbalance = 1.0 + r.normal(0, 0.08, 4)   # cylinder-to-cylinder variation

    def render(self, n, rpm, load, boost_psi, throttle, cut, limiter=False):
        """n samples for the current state. load 0..1, throttle 0..1, cut 0..1."""
        sr = self.sr
        out = np.zeros(n + len(self.tail), np.float32)
        out[:len(self.tail)] += self.tail
        rate = max(rpm, 0.0) / 30.0                       # firings per second
        if rate > 1:
            p0 = self.phase
            p1 = p0 + rate * n / sr
            for k in range(int(np.ceil(p0)), int(np.floor(p1)) + 1):
                pos = int((k - p0) / rate * sr)
                if pos < 0 or pos >= n:
                    continue
                if limiter and (k % 3 != 0):              # rev limiter: fuel cut on most events
                    continue
                amp = (0.18 + 0.82 * load) * self.imbalance[k % 4] * (1.0 + 0.04 * self.rng.normal())
                if cut > 0.05:
                    # retarded firing: quieter in the cylinder, late, and now
                    # and then the unburned charge lights in the pipe
                    amp *= 1.0 - 0.6 * cut
                    pos += int(self.rng.uniform(0.001, 0.004) * sr)
                    if self.rng.random() < 0.10 * cut:
                        pulse, amp = self.pop, (0.9 + 0.8 * cut) * (0.18 + 0.82 * load)
                    else:
                        pulse = self.hard
                else:
                    pulse = (1.0 - load) * self.soft + load * self.hard
                end = min(pos + len(pulse), len(out))
                out[pos:end] += amp * pulse[:end - pos]
            self.phase = p1
        # turbo: whistle pitch and level follow boost, with a whoosh under it
        b = max(boost_psi, 0.0) / 20.0
        if b > 0.02:
            t = np.arange(n) / sr
            f = 1800.0 + 2600.0 * b
            ph = self.turbo_phase + 2 * np.pi * f * t
            out[:n] += (0.035 * b) * np.sin(ph).astype(np.float32)
            self.turbo_phase = float(ph[-1] % (2 * np.pi))
            wh = self.rng.normal(0, 1, n).astype(np.float32)
            out[:n] += (0.05 * b) * np.convolve(wh, np.ones(40) / 40, mode="same")
        # intake hiss with throttle
        if throttle > 0.05:
            hs = self.rng.normal(0, 1, n).astype(np.float32)
            out[:n] += (0.03 * throttle) * np.convolve(hs, np.ones(6) / 6, mode="same")
        block, self.tail = out[:n], out[n:]
        return np.clip(block, -1.0, 1.0)


def write_wav(path, samples, sr=SR):
    import wave
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(data.tobytes())
