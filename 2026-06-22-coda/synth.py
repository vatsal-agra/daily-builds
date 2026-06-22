"""Waveform synthesizer with ADSR envelopes and polyphonic voice allocator."""

import math
from wav import AudioBuffer, SAMPLE_RATE, midi_note_to_hz


# ---------------------------------------------------------------------------
# Waveform generators
# ---------------------------------------------------------------------------

def sine_wave(freq: float, num_samples: int, phase: float = 0.0) -> list[float]:
    """Generate a pure sine wave."""
    TAU = 2.0 * math.pi
    step = TAU * freq / SAMPLE_RATE
    return [math.sin(phase + i * step) for i in range(num_samples)]


def square_wave(freq: float, num_samples: int, phase: float = 0.0,
                harmonics: int = 15) -> list[float]:
    """Band-limited square wave via additive synthesis (odd harmonics)."""
    TAU = 2.0 * math.pi
    step = TAU * freq / SAMPLE_RATE
    samples = [0.0] * num_samples
    for k in range(1, harmonics * 2, 2):
        f_k = freq * k
        if f_k >= SAMPLE_RATE / 2:
            break
        amp = 1.0 / k
        for i in range(num_samples):
            samples[i] += amp * math.sin(phase + i * step * k)
    # normalize to [-1, 1]
    peak = max(abs(s) for s in samples) or 1.0
    scale = 1.0 / peak
    return [s * scale for s in samples]


def sawtooth_wave(freq: float, num_samples: int, phase: float = 0.0,
                  harmonics: int = 20) -> list[float]:
    """Band-limited sawtooth wave via additive synthesis."""
    TAU = 2.0 * math.pi
    step = TAU * freq / SAMPLE_RATE
    samples = [0.0] * num_samples
    for k in range(1, harmonics + 1):
        f_k = freq * k
        if f_k >= SAMPLE_RATE / 2:
            break
        amp = 1.0 / k
        sign = 1.0 if k % 2 == 1 else -1.0
        for i in range(num_samples):
            samples[i] += sign * amp * math.sin(phase + i * step * k)
    peak = max(abs(s) for s in samples) or 1.0
    scale = 1.0 / peak
    return [s * scale for s in samples]


def triangle_wave(freq: float, num_samples: int, phase: float = 0.0) -> list[float]:
    """Band-limited triangle wave (odd harmonics, alternating sign, 1/k^2)."""
    TAU = 2.0 * math.pi
    step = TAU * freq / SAMPLE_RATE
    samples = [0.0] * num_samples
    sign = 1.0
    for k in range(1, 30, 2):
        f_k = freq * k
        if f_k >= SAMPLE_RATE / 2:
            break
        amp = sign / (k * k)
        for i in range(num_samples):
            samples[i] += amp * math.sin(phase + i * step * k)
        sign = -sign
    peak = max(abs(s) for s in samples) or 1.0
    scale = 1.0 / peak
    return [s * scale for s in samples]


def noise_burst(num_samples: int, seed: int = 0) -> list[float]:
    """Deterministic white noise (for drums/percussives)."""
    # LCG random to avoid importing random (keeps it pure)
    a, c, m = 1664525, 1013904223, 2**32
    state = seed & 0xFFFFFFFF
    samples = []
    for _ in range(num_samples):
        state = (a * state + c) & (m - 1)
        samples.append((state / (m / 2)) - 1.0)
    return samples


# ---------------------------------------------------------------------------
# ADSR Envelope
# ---------------------------------------------------------------------------

class ADSR:
    """Attack-Decay-Sustain-Release envelope generator.

    All times are in seconds. `sustain` is a level in [0, 1].
    """

    def __init__(self, attack: float = 0.01, decay: float = 0.05,
                 sustain: float = 0.7, release: float = 0.1):
        self.attack = max(0.001, attack)
        self.decay = max(0.001, decay)
        self.sustain = max(0.0, min(1.0, sustain))
        self.release = max(0.001, release)

    def envelope(self, duration_s: float) -> list[float]:
        """Return a list of per-sample gain values for a note held for `duration_s`
        seconds (note-on to note-off), followed by the release tail."""
        a_samps = int(self.attack * SAMPLE_RATE)
        d_samps = int(self.decay * SAMPLE_RATE)
        r_samps = int(self.release * SAMPLE_RATE)
        hold_samps = max(0, int(duration_s * SAMPLE_RATE) - a_samps - d_samps)
        total = a_samps + d_samps + hold_samps + r_samps
        env = []
        # Attack: 0 → 1
        for i in range(a_samps):
            env.append(i / a_samps)
        # Decay: 1 → sustain
        for i in range(d_samps):
            env.append(1.0 - (1.0 - self.sustain) * (i / d_samps))
        # Sustain
        for _ in range(hold_samps):
            env.append(self.sustain)
        # Release: sustain → 0
        for i in range(r_samps):
            env.append(self.sustain * (1.0 - i / r_samps))
        return env

    def apply(self, samples: list[float], duration_s: float) -> list[float]:
        env = self.envelope(duration_s)
        # Trim or extend to match samples length
        if len(env) < len(samples):
            env = env + [0.0] * (len(samples) - len(env))
        return [samples[i] * env[i] for i in range(len(samples))]


# ---------------------------------------------------------------------------
# Voice: a single sounding note
# ---------------------------------------------------------------------------

class VoiceParams:
    """Parameters for synthesizing a single note."""
    def __init__(
        self,
        waveform: str = "sine",
        adsr: ADSR | None = None,
        harmonics: list[tuple[float, float]] | None = None,  # (freq_ratio, amp_ratio)
        detune_cents: float = 0.0,
        fm_ratio: float = 0.0,
        fm_depth: float = 0.0,
    ):
        self.waveform = waveform
        self.adsr = adsr or ADSR()
        self.harmonics = harmonics or []
        self.detune_cents = detune_cents
        self.fm_ratio = fm_ratio
        self.fm_depth = fm_depth


def render_voice(
    midi_note: int,
    velocity: int,
    duration_s: float,
    pan: float,  # -1.0 (left) to +1.0 (right)
    params: VoiceParams,
) -> AudioBuffer:
    """Render a single note to an AudioBuffer."""
    base_freq = midi_note_to_hz(midi_note)
    # Apply detune
    if params.detune_cents:
        base_freq *= 2 ** (params.detune_cents / 1200)
    vel_gain = (velocity / 127) ** 0.7  # mild compression

    # Total samples including ADSR release tail
    release_samples = int(params.adsr.release * SAMPLE_RATE)
    hold_samples = max(1, int(duration_s * SAMPLE_RATE))
    total_samples = hold_samples + release_samples

    # FM modulation
    if params.fm_ratio > 0 and params.fm_depth > 0:
        mod_freq = base_freq * params.fm_ratio
        TAU = 2.0 * math.pi
        mod_step = TAU * mod_freq / SAMPLE_RATE
        modulator = [params.fm_depth * math.sin(i * mod_step) for i in range(total_samples)]
    else:
        modulator = [0.0] * total_samples

    # Build primary waveform
    TAU = 2.0 * math.pi
    carrier_step = TAU * base_freq / SAMPLE_RATE
    raw = []
    if params.waveform == "sine":
        for i in range(total_samples):
            raw.append(math.sin(i * carrier_step + modulator[i]))
    elif params.waveform == "square":
        for i in range(total_samples):
            raw.append(1.0 if math.sin(i * carrier_step + modulator[i]) >= 0 else -1.0)
    elif params.waveform == "sawtooth":
        for i in range(total_samples):
            phase = ((i * base_freq / SAMPLE_RATE + modulator[i] / TAU) % 1.0)
            raw.append(2.0 * phase - 1.0)
    elif params.waveform == "triangle":
        for i in range(total_samples):
            phase = ((i * base_freq / SAMPLE_RATE + modulator[i] / TAU) % 1.0)
            raw.append(4.0 * abs(phase - 0.5) - 1.0)
    elif params.waveform == "noise":
        raw = noise_burst(total_samples, seed=midi_note)
    else:
        raw = [math.sin(i * carrier_step) for i in range(total_samples)]

    # Add harmonics (additive synthesis)
    if params.harmonics:
        for freq_ratio, amp_ratio in params.harmonics:
            h_freq = base_freq * freq_ratio
            if h_freq >= SAMPLE_RATE / 2:
                continue
            h_step = TAU * h_freq / SAMPLE_RATE
            for i in range(total_samples):
                raw[i] += amp_ratio * math.sin(i * h_step)
        # re-normalize
        peak = max(abs(s) for s in raw) or 1.0
        scale = 1.0 / peak
        raw = [s * scale for s in raw]

    # Apply ADSR
    env = params.adsr.envelope(duration_s)
    if len(env) < total_samples:
        env = env + [0.0] * (total_samples - len(env))
    raw = [raw[i] * env[i] for i in range(total_samples)]

    # Pan law: constant power
    pan_l = math.cos((pan + 1) * math.pi / 4)
    pan_r = math.sin((pan + 1) * math.pi / 4)

    buf = AudioBuffer(total_samples)
    for i in range(total_samples):
        s = raw[i] * vel_gain
        buf.left[i] = s * pan_l
        buf.right[i] = s * pan_r
    return buf


# ---------------------------------------------------------------------------
# Polyphonic mixer
# ---------------------------------------------------------------------------

class PolySynth:
    """Accumulates rendered voices into a single AudioBuffer."""

    def __init__(self, total_samples: int):
        self.buf = AudioBuffer(total_samples)

    def play(self, midi_note: int, velocity: int, start_sample: int,
             duration_s: float, pan: float, params: VoiceParams):
        """Schedule a note event."""
        voice_buf = render_voice(midi_note, velocity, duration_s, pan, params)
        self.buf.mix_into(voice_buf, offset=start_sample, gain=0.5)

    def get_buffer(self) -> AudioBuffer:
        return self.buf
