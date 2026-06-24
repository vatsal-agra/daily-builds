"""Audio effects: delay, Freeverb reverb, distortion, chorus.

All effects operate on mono float sample lists and return mono float lists.
For stereo effects (reverb), separate L/R instances are used with a spread offset.
"""

import math

_TWO_PI = 2.0 * math.pi

# ---------------------------------------------------------------------------
# Delay / echo
# ---------------------------------------------------------------------------

class Delay:
    """Circular-buffer delay with feedback and high-frequency damping."""

    def __init__(self, delay_s: float, feedback: float, damping: float = 0.3,
                 sr: int = 44100):
        self.delay_n = max(1, int(delay_s * sr))
        self.feedback = feedback
        self.damping = damping
        self.buf = [0.0] * (self.delay_n + 1)
        self.pos = 0
        self._lp = 0.0  # one-pole LP state for damping

    def process(self, samples: list, wet: float = 0.4) -> list:
        out = []
        buf, pos = self.buf, self.pos
        fb, damp, damp_inv = self.feedback, self.damping, 1.0 - self.damping
        lp = self._lp
        n = len(buf)
        for x in samples:
            delayed = buf[pos]
            lp = delayed * damp_inv + lp * damp
            buf[pos] = x + lp * fb
            pos = (pos + 1) % n
            out.append(x + delayed * wet)
        self.pos = pos
        self._lp = lp
        return out


# ---------------------------------------------------------------------------
# Freeverb reverb
# ---------------------------------------------------------------------------

# Freeverb tuning (samples at 44100 Hz)
_COMB_DELAYS = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
_ALLPASS_DELAYS = [556, 441, 341, 225]
_STEREO_SPREAD = 23


class _LBCF:
    """Lowpass-feedback comb filter (Freeverb building block)."""

    def __init__(self, delay_n: int, room_size: float, damping: float):
        self.buf = [0.0] * delay_n
        self.pos = 0
        self.feedback = room_size
        self.damp = damping
        self.damp_inv = 1.0 - damping
        self._lp = 0.0

    def tick(self, x: float) -> float:
        output = self.buf[self.pos]
        self._lp = output * self.damp_inv + self._lp * self.damp
        self.buf[self.pos] = x + self._lp * self.feedback
        self.pos = (self.pos + 1) % len(self.buf)
        return output


class _AllPass:
    """All-pass filter (Freeverb diffuser)."""

    def __init__(self, delay_n: int):
        self.buf = [0.0] * delay_n
        self.pos = 0
        self.feedback = 0.5

    def tick(self, x: float) -> float:
        buf_out = self.buf[self.pos]
        output = -x + buf_out
        self.buf[self.pos] = x + buf_out * self.feedback
        self.pos = (self.pos + 1) % len(self.buf)
        return output


class Reverb:
    """Freeverb stereo reverb: 8 LBCF (parallel) + 4 all-pass (series) per channel."""

    def __init__(self, room_size: float = 0.5, damping: float = 0.5,
                 sr: int = 44100, wet: float = 0.3, dry: float = 0.7):
        scale = sr / 44100.0
        room = room_size * 0.28 + 0.7   # Freeverb scaling
        damp = damping * 0.4

        self.combs_l = [_LBCF(max(1, int(d * scale)), room, damp)
                        for d in _COMB_DELAYS]
        self.combs_r = [_LBCF(max(1, int((d + _STEREO_SPREAD) * scale)), room, damp)
                        for d in _COMB_DELAYS]
        self.aps_l = [_AllPass(max(1, int(d * scale))) for d in _ALLPASS_DELAYS]
        self.aps_r = [_AllPass(max(1, int((d + _STEREO_SPREAD) * scale)))
                      for d in _ALLPASS_DELAYS]
        self.wet = wet
        self.dry = dry

    def process_mono_to_stereo(self, samples: list) -> tuple:
        """Process mono input → (left_samples, right_samples)."""
        gain = 0.015
        out_l = []
        out_r = []
        for x in samples:
            inp = x * gain
            # Sum comb filter outputs (parallel)
            sl = sum(c.tick(inp) for c in self.combs_l)
            sr = sum(c.tick(inp) for c in self.combs_r)
            # Series all-pass filters (diffusion)
            for ap in self.aps_l:
                sl = ap.tick(sl)
            for ap in self.aps_r:
                sr = ap.tick(sr)
            out_l.append(x * self.dry + sl * self.wet)
            out_r.append(x * self.dry + sr * self.wet)
        return out_l, out_r

    def process_stereo(self, left: list, right: list) -> tuple:
        """Process stereo input → (left_out, right_out)."""
        gain = 0.015
        out_l = []
        out_r = []
        for xl, xr in zip(left, right):
            inp = (xl + xr) * 0.5 * gain
            sl = sum(c.tick(inp) for c in self.combs_l)
            sr = sum(c.tick(inp) for c in self.combs_r)
            for ap in self.aps_l:
                sl = ap.tick(sl)
            for ap in self.aps_r:
                sr = ap.tick(sr)
            out_l.append(xl * self.dry + sl * self.wet)
            out_r.append(xr * self.dry + sr * self.wet)
        return out_l, out_r


# ---------------------------------------------------------------------------
# Distortion / saturation
# ---------------------------------------------------------------------------

def soft_clip(samples: list, drive: float = 2.0, makeup: float = 1.0) -> list:
    """Hyperbolic tangent soft-clip. drive > 1 = more saturation.

    Normalised so x=±1 maps to ±1. For |x| > 1 the output is clamped to ±1.
    """
    drive = max(0.1, drive)
    norm = math.tanh(drive)
    return [max(-1.0, min(1.0, math.tanh(x * drive) / norm * makeup))
            for x in samples]


# ---------------------------------------------------------------------------
# Chorus
# ---------------------------------------------------------------------------

class Chorus:
    """LFO-modulated delay line chorus / flanger."""

    def __init__(self, rate: float = 0.5, depth: float = 0.003,
                 base_delay: float = 0.02, sr: int = 44100, wet: float = 0.4):
        self.sr = sr
        self.rate = rate
        self.depth_s = depth
        self.base_delay_s = base_delay
        self.wet = wet
        max_delay_n = int((base_delay + depth) * sr) + 4
        self.buf = [0.0] * max_delay_n
        self.write_pos = 0
        self.lfo_phase = 0.0

    def process(self, samples: list) -> list:
        out = []
        sr = self.sr
        buf = self.buf
        n = len(buf)
        phase = self.lfo_phase
        dt = self.rate / sr
        base_d = self.base_delay_s * sr
        depth_d = self.depth_s * sr
        wet = self.wet

        for x in samples:
            # LFO value
            lfo = math.sin(_TWO_PI * phase)
            phase = (phase + dt) % 1.0

            # Modulated delay in samples
            delay_samp = base_d + depth_d * lfo
            delay_int = int(delay_samp)
            frac = delay_samp - delay_int

            # Read with linear interpolation
            r0 = (self.write_pos - delay_int - 1 + n) % n
            r1 = (r0 + 1) % n
            delayed = buf[r0] * (1.0 - frac) + buf[r1] * frac

            buf[self.write_pos] = x
            self.write_pos = (self.write_pos + 1) % n
            out.append(x * (1.0 - wet) + delayed * wet)

        self.lfo_phase = phase
        return out


# ---------------------------------------------------------------------------
# Master limiter / normaliser
# ---------------------------------------------------------------------------

def normalize_peak(left: list, right: list, target: float = 0.88) -> tuple:
    """Scale L+R so the peak sample equals target."""
    peak = max((abs(s) for s in left + right), default=1.0)
    if peak < 1e-9:
        return left, right
    scale = target / peak
    return [s * scale for s in left], [s * scale for s in right]


def soft_limit(samples: list, threshold: float = 0.9) -> list:
    """Gentle knee limiter that keeps output in (-1, 1).

    Below threshold: unity gain. Above threshold: soft-knee compression
    that asymptotically approaches 1.0 as input → ∞.
    """
    headroom = 1.0 - threshold
    out = []
    for s in samples:
        a = abs(s)
        if a <= threshold:
            out.append(s)
        else:
            sign = 1.0 if s > 0 else -1.0
            excess = a - threshold
            # Compresses the excess into (0, headroom); asymptotically → 1.0
            compressed = threshold + headroom * (1.0 - 1.0 / (1.0 + excess / headroom))
            out.append(sign * compressed)
    return out
