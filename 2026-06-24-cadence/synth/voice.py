"""Full synthesis voice: oscillator + ADSR envelope + biquad filter + LFO.

render_note() is the main entry point. It renders a single note event into
a float sample list (gate + release). All computation is done offline (not
real-time), which allows list comprehensions for the non-stateful parts.
"""

import math
import random as _random

from .core import note_to_freq, SAMPLE_RATE, TWO_PI
from .oscillator import generate, accumulate_phases, accumulate_phases_fm
from .envelope import compute_adsr, apply_env
from .filter import apply_filter, get_coeffs

_SR = SAMPLE_RATE


def _default_preset():
    return {
        'oscillator': 'sawtooth',
        'pw': 0.5,
        'detune_cents': 0.0,
        'sub_mix': 0.0,
        'attack': 0.01,
        'decay': 0.1,
        'sustain': 0.7,
        'release': 0.15,
        'filter_type': 'lpf',
        'cutoff': 8000.0,
        'resonance': 1.0,
        'filter_env_amount': 0.0,
        'lfo_rate': 5.0,
        'lfo_depth': 0.0,
        'lfo_target': 'pitch',
        'lfo_waveform': 'sine',
        'volume': 0.8,
    }


def _lfo_samples(rate: float, waveform: str, n: int) -> list:
    """Generate n LFO samples in [-1, 1]."""
    dt = rate / _SR
    if waveform == 'sine':
        return [math.sin(TWO_PI * dt * i) for i in range(n)]
    elif waveform == 'square':
        return [1.0 if (dt * i % 1.0) < 0.5 else -1.0 for i in range(n)]
    elif waveform == 'sawtooth':
        return [2.0 * (dt * i % 1.0) - 1.0 for i in range(n)]
    else:
        return [math.sin(TWO_PI * dt * i) for i in range(n)]


def render_note(preset: dict, midi_pitch: int, velocity: int,
                gate_samples: int, rng=None) -> list:
    """Render a single note into a float sample list.

    The list length is gate_samples + release_samples. The caller is
    responsible for adding it into the mix buffer at the correct offset.
    """
    if rng is None:
        rng = _random

    p = {**_default_preset(), **preset}
    freq = note_to_freq(midi_pitch)
    vel_scale = velocity / 127.0
    volume = p['volume'] * vel_scale

    attack_s = float(p['attack'])
    decay_s = float(p['decay'])
    sustain_lvl = float(p['sustain'])
    release_s = float(p['release'])
    release_n = max(int(release_s * _SR), 1)
    total_n = gate_samples + release_n

    # ---- LFO ----------------------------------------------------------------
    lfo_depth = float(p['lfo_depth'])
    lfo_target = p['lfo_target']
    lfo_vals = _lfo_samples(float(p['lfo_rate']), p['lfo_waveform'], total_n) \
               if lfo_depth > 0 else None

    # ---- Oscillator ---------------------------------------------------------
    dt = freq / _SR
    osc_type = p['oscillator']

    if lfo_depth > 0 and lfo_target == 'pitch':
        # Per-sample frequency modulation (vibrato) — need phase accumulation
        semitone_depth = lfo_depth  # depth in semitones
        freqs = [freq * (2.0 ** (semitone_depth * lv / 12.0))
                 for lv in lfo_vals]
        phases, _ = accumulate_phases_fm(0.0, freqs, _SR)
        dt = freq / _SR  # approximate dt for PolyBLEP
    else:
        phases, _ = accumulate_phases(0.0, freq, _SR, total_n)

    osc_samples = generate(osc_type, phases, dt, float(p['pw']), rng)

    # ---- Optional detuned sub-oscillator ------------------------------------
    sub_mix = float(p['sub_mix'])
    if sub_mix > 0:
        detune_ratio = 2.0 ** (float(p['detune_cents']) / 1200.0)
        freq2 = freq * detune_ratio
        dt2 = freq2 / _SR
        phases2, _ = accumulate_phases(0.0, freq2, _SR, total_n)
        sub_samples = generate(osc_type, phases2, dt2, float(p['pw']), rng)
        osc_samples = [o * (1.0 - sub_mix) + s * sub_mix
                       for o, s in zip(osc_samples, sub_samples)]

    # ---- ADSR envelope ------------------------------------------------------
    env = compute_adsr(gate_samples, release_n, attack_s, decay_s,
                       sustain_lvl, release_s, _SR)
    voiced = apply_env(osc_samples, env)

    # ---- Amplitude modulation (tremolo) -------------------------------------
    if lfo_depth > 0 and lfo_target == 'amp' and lfo_vals is not None:
        am_depth = min(lfo_depth, 1.0)
        voiced = [v * (1.0 + am_depth * lfo_vals[i] * 0.5)
                  for i, v in enumerate(voiced)]

    # ---- Biquad filter ------------------------------------------------------
    ftype = p['filter_type']
    if ftype != 'none':
        base_cutoff = float(p['cutoff'])
        q = max(float(p['resonance']), 0.1)

        # Filter envelope: cutoff shifts by filter_env_amount semitones at peak
        fenv_amount = float(p['filter_env_amount'])

        if fenv_amount != 0.0 or (lfo_depth > 0 and lfo_target == 'filter'):
            # Block processing: recompute coefficients every 64 samples
            BLOCK = 64
            out = []
            state = None
            for blk_start in range(0, len(voiced), BLOCK):
                blk = voiced[blk_start:blk_start + BLOCK]
                mid = blk_start + len(blk) // 2

                # Filter envelope modulation
                if fenv_amount != 0.0 and mid < len(env):
                    env_level = env[mid]
                    cutoff = base_cutoff * (2.0 ** (fenv_amount * env_level / 12.0))
                else:
                    cutoff = base_cutoff

                # LFO filter modulation
                if lfo_depth > 0 and lfo_target == 'filter' and lfo_vals is not None:
                    lv = lfo_vals[min(mid, len(lfo_vals) - 1)]
                    cutoff *= (2.0 ** (lfo_depth * lv / 12.0))

                cutoff = max(20.0, min(cutoff, _SR * 0.499))
                b0, b1, b2, a1, a2 = get_coeffs(ftype, cutoff, q, _SR)
                blk_out, state = _apply_filter_inline(blk, b0, b1, b2, a1, a2, state)
                out.extend(blk_out)
        else:
            # Static filter — one pass
            from .filter import apply_filter_block
            out, _ = apply_filter_block(voiced, ftype, base_cutoff, q, _SR)
    else:
        out = voiced

    # ---- Volume -------------------------------------------------------------
    return [s * volume for s in out]


def _apply_filter_inline(samples, b0, b1, b2, a1, a2, state):
    """Tight per-sample biquad loop, reused by block processing."""
    if state is not None:
        x1, x2, y1, y2 = state
    else:
        x1 = x2 = y1 = y2 = 0.0
    out = []
    for x0 in samples:
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, x0
        y2, y1 = y1, y0
        out.append(y0)
    return out, (x1, x2, y1, y2)


def render_drum(kind: str, velocity: int, sr: int = _SR, rng=None) -> list:
    """Synthesize a drum hit as a float sample list.

    kind: 'kick', 'snare', 'hihat', 'clap'
    """
    if rng is None:
        rng = _random
    vel = velocity / 127.0

    if kind == 'kick':
        # Sine with exponential pitch drop from 200 Hz → 50 Hz, short envelope
        dur = int(0.35 * sr)
        out = []
        for i in range(dur):
            t = i / sr
            # Pitch envelope: 200 → 50 Hz exponential decay over 0.15s
            f = 50.0 + 150.0 * math.exp(-t / 0.06)
            # Amplitude envelope
            amp = math.exp(-t / 0.2)
            out.append(math.sin(TWO_PI * f * t) * amp * vel * 0.9)
        return out

    elif kind == 'snare':
        # Short sine (body) + bandpass noise (crack), very fast decay
        dur = int(0.18 * sr)
        out = []
        # Noise component (bandpass filtered)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(dur)]
        # Simple bandpass: HP at 500 Hz + LP at 6000 Hz
        from .filter import lpf_coeffs, hpf_coeffs
        from .filter import apply_filter
        b0, b1, b2, a1, a2 = lpf_coeffs(6000.0, 1.0, sr)
        noise, _ = apply_filter(noise, b0, b1, b2, a1, a2)
        b0, b1, b2, a1, a2 = hpf_coeffs(500.0, 1.0, sr)
        noise, _ = apply_filter(noise, b0, b1, b2, a1, a2)

        for i in range(dur):
            t = i / sr
            body = math.sin(TWO_PI * 180.0 * t) * math.exp(-t / 0.03)
            crack = noise[i] * math.exp(-t / 0.08)
            out.append((body * 0.4 + crack * 0.6) * vel * 0.85)
        return out

    elif kind == 'hihat':
        # Very short bandpass noise, bright
        dur = int(0.05 * sr)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(dur)]
        from .filter import hpf_coeffs, apply_filter
        b0, b1, b2, a1, a2 = hpf_coeffs(8000.0, 0.8, sr)
        noise, _ = apply_filter(noise, b0, b1, b2, a1, a2)
        return [noise[i] * math.exp(-i / (dur * 0.4)) * vel * 0.5
                for i in range(dur)]

    elif kind == 'open_hihat':
        dur = int(0.25 * sr)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(dur)]
        from .filter import hpf_coeffs, apply_filter
        b0, b1, b2, a1, a2 = hpf_coeffs(7000.0, 0.8, sr)
        noise, _ = apply_filter(noise, b0, b1, b2, a1, a2)
        return [noise[i] * math.exp(-i / (dur * 0.5)) * vel * 0.45
                for i in range(dur)]

    elif kind == 'clap':
        dur = int(0.12 * sr)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(dur)]
        from .filter import bpf_coeffs, apply_filter
        b0, b1, b2, a1, a2 = bpf_coeffs(1500.0, 2.0, sr)
        noise, _ = apply_filter(noise, b0, b1, b2, a1, a2)
        # Multi-burst attack
        out = []
        for i in range(dur):
            t = i / sr
            burst = (math.exp(-t / 0.002) + 0.5 * math.exp(-(t - 0.005) / 0.002)
                     if t > 0.005 else math.exp(-t / 0.002))
            out.append(noise[i] * burst * vel * 0.7)
        return out
    else:
        return []
