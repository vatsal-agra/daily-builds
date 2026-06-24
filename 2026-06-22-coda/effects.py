"""DSP effects chain: Biquad LPF, Schroeder reverb, ping-pong delay.

All filters operate sample-by-sample on a stereo AudioBuffer.
Math references:
  - Biquad: Audio EQ Cookbook (Zolzer)
  - Schroeder reverb: Moorer 1979, Schroeder 1962
"""

import math
from wav import AudioBuffer, SAMPLE_RATE


# ---------------------------------------------------------------------------
# Biquad low-pass filter
# ---------------------------------------------------------------------------

class BiquadLPF:
    """Second-order IIR low-pass filter designed via the bilinear transform.

    Cutoff in Hz, Q is the resonance quality factor (0.707 = Butterworth).
    Applied independently to left and right channels.
    """

    def __init__(self, cutoff_hz: float, q: float = 0.707):
        self._design(cutoff_hz, q)
        # State variables per channel: (x1, x2, y1, y2)
        self._state_l = [0.0, 0.0, 0.0, 0.0]
        self._state_r = [0.0, 0.0, 0.0, 0.0]

    def _design(self, cutoff_hz: float, q: float):
        """Compute biquad coefficients."""
        w0 = 2.0 * math.pi * cutoff_hz / SAMPLE_RATE
        alpha = math.sin(w0) / (2.0 * q)
        cos_w0 = math.cos(w0)

        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def _process_sample(self, x: float, state: list) -> float:
        x1, x2, y1, y2 = state
        y = self.b0 * x + self.b1 * x1 + self.b2 * x2 - self.a1 * y1 - self.a2 * y2
        state[0] = x
        state[1] = x1
        state[2] = y
        state[3] = y1
        return y

    def process(self, buf: AudioBuffer) -> AudioBuffer:
        """Apply the filter in-place and return buf."""
        for i in range(buf.num_samples):
            buf.left[i] = self._process_sample(buf.left[i], self._state_l)
            buf.right[i] = self._process_sample(buf.right[i], self._state_r)
        return buf


# ---------------------------------------------------------------------------
# Schroeder reverb
# ---------------------------------------------------------------------------

class CombFilter:
    """Feedback comb filter with fixed delay and gain."""

    def __init__(self, delay_samples: int, feedback: float, damp: float = 0.5):
        self.buffer = [0.0] * delay_samples
        self.size = delay_samples
        self.feedback = feedback
        self.damp = damp
        self.filterstore = 0.0
        self.idx = 0

    def process(self, x: float) -> float:
        output = self.buffer[self.idx]
        self.filterstore = output * (1.0 - self.damp) + self.filterstore * self.damp
        self.buffer[self.idx] = x + self.filterstore * self.feedback
        self.idx = (self.idx + 1) % self.size
        return output


class AllPassFilter:
    """Schroeder allpass filter."""

    def __init__(self, delay_samples: int, feedback: float = 0.5):
        self.buffer = [0.0] * delay_samples
        self.size = delay_samples
        self.feedback = feedback
        self.idx = 0

    def process(self, x: float) -> float:
        bufout = self.buffer[self.idx]
        output = -x + bufout
        self.buffer[self.idx] = x + bufout * self.feedback
        self.idx = (self.idx + 1) % self.size
        return output


class SchroederReverb:
    """Classic Schroeder/Moorer reverb: 4 parallel comb filters → 2 allpass.

    room_size in [0, 1], wet in [0, 1].
    """

    COMB_DELAYS = [1116, 1188, 1277, 1356]   # samples at 44100 Hz
    ALLPASS_DELAYS = [556, 441]
    STEREO_SPREAD = 23

    def __init__(self, room_size: float = 0.5, wet: float = 0.25,
                 damp: float = 0.5):
        self.wet = wet
        self.dry = 1.0 - wet

        feedback = 0.84 + room_size * 0.12

        # Left and right comb filters (right has a small stereo spread)
        self.combs_l = [
            CombFilter(d, feedback, damp) for d in self.COMB_DELAYS
        ]
        self.combs_r = [
            CombFilter(d + self.STEREO_SPREAD, feedback, damp)
            for d in self.COMB_DELAYS
        ]
        self.aps_l = [AllPassFilter(d) for d in self.ALLPASS_DELAYS]
        self.aps_r = [AllPassFilter(d + self.STEREO_SPREAD) for d in self.ALLPASS_DELAYS]

    def process(self, buf: AudioBuffer) -> AudioBuffer:
        """Apply reverb in-place."""
        for i in range(buf.num_samples):
            x_l = buf.left[i]
            x_r = buf.right[i]
            x_mono = (x_l + x_r) * 0.5

            out_l = sum(c.process(x_mono) for c in self.combs_l)
            out_r = sum(c.process(x_mono) for c in self.combs_r)

            for ap in self.aps_l:
                out_l = ap.process(out_l)
            for ap in self.aps_r:
                out_r = ap.process(out_r)

            buf.left[i] = x_l * self.dry + out_l * self.wet * 0.015
            buf.right[i] = x_r * self.dry + out_r * self.wet * 0.015

        return buf


# ---------------------------------------------------------------------------
# Ping-pong delay
# ---------------------------------------------------------------------------

class PingPongDelay:
    """Stereo ping-pong delay: wet signal alternates between L and R channels.

    delay_ms: delay time in milliseconds.
    feedback: feedback gain [0, 1).
    wet: wet/dry mix [0, 1].
    """

    def __init__(self, delay_ms: float = 375.0, feedback: float = 0.4,
                 wet: float = 0.2):
        self.delay_samples = int(delay_ms * SAMPLE_RATE / 1000)
        self.feedback = feedback
        self.wet = wet
        self.dry = 1.0 - wet
        size = self.delay_samples + 1
        self.buf_l = [0.0] * size
        self.buf_r = [0.0] * size
        self.idx = 0

    def process(self, buf: AudioBuffer) -> AudioBuffer:
        size = len(self.buf_l)
        for i in range(buf.num_samples):
            read_idx = (self.idx - self.delay_samples) % size
            delayed_l = self.buf_l[read_idx]
            delayed_r = self.buf_r[read_idx]

            # Ping-pong: left delay feeds right, right feeds left
            new_l = buf.left[i] + delayed_r * self.feedback
            new_r = buf.right[i] + delayed_l * self.feedback

            self.buf_l[self.idx] = new_l
            self.buf_r[self.idx] = new_r
            self.idx = (self.idx + 1) % size

            buf.left[i] = buf.left[i] * self.dry + delayed_l * self.wet
            buf.right[i] = buf.right[i] * self.dry + delayed_r * self.wet

        return buf


# ---------------------------------------------------------------------------
# Convenience: apply a named chain to a buffer
# ---------------------------------------------------------------------------

def apply_effects(
    buf: AudioBuffer,
    reverb: bool = True,
    delay: bool = True,
    lpf: bool = True,
    room_size: float = 0.5,
    reverb_wet: float = 0.25,
    delay_ms: float = 375.0,
    delay_feedback: float = 0.35,
    delay_wet: float = 0.18,
    lpf_cutoff: float = 12000.0,
    lpf_q: float = 0.707,
) -> AudioBuffer:
    """Apply selected effects in order: LPF → reverb → delay."""
    if lpf:
        BiquadLPF(lpf_cutoff, lpf_q).process(buf)
    if reverb:
        SchroederReverb(room_size, reverb_wet).process(buf)
    if delay:
        PingPongDelay(delay_ms, delay_feedback, delay_wet).process(buf)
    buf.normalize()
    return buf
