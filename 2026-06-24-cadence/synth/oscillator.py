"""Waveform oscillators with PolyBLEP antialiasing.

Each generate() call returns a list of float samples in [-1, 1].
Phase is accumulated by the caller (see voice.py).
"""

import math

_TWO_PI = 2.0 * math.pi


def _poly_blep(t: float, dt: float) -> float:
    """PolyBLEP transition correction for a rising step at t=0.

    Near t=0 (just after the step): smooths the abrupt jump upward.
    Near t=1 (just before the step): smooths the approach from below.
    Returns 0 outside the two correction windows.
    """
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


def gen_sine(phases: list) -> list:
    """Pure sine wave — no aliasing, no correction needed."""
    return [math.sin(_TWO_PI * p) for p in phases]


def gen_sawtooth(phases: list, dt: float) -> list:
    """Rising sawtooth with PolyBLEP correction at the reset discontinuity."""
    return [2.0 * p - 1.0 - _poly_blep(p, dt) for p in phases]


def gen_rsaw(phases: list, dt: float) -> list:
    """Falling (reverse) sawtooth with PolyBLEP correction."""
    return [1.0 - 2.0 * p + _poly_blep(p, dt) for p in phases]


def gen_square(phases: list, dt: float) -> list:
    """Square wave with PolyBLEP at both rising (t=0) and falling (t=0.5) edges."""
    out = []
    for p in phases:
        s = 1.0 if p < 0.5 else -1.0
        s += _poly_blep(p, dt)
        s -= _poly_blep((p + 0.5) % 1.0, dt)
        out.append(s)
    return out


def gen_triangle(phases: list) -> list:
    """Band-limited triangle wave (naturally rolls off at 1/n²; no PolyBLEP needed)."""
    out = []
    for p in phases:
        if p < 0.5:
            out.append(4.0 * p - 1.0)
        else:
            out.append(3.0 - 4.0 * p)
    return out


def gen_pulse(phases: list, dt: float, pw: float = 0.5) -> list:
    """Variable-width pulse wave with PolyBLEP at both edges.

    pw=0.5 is a square wave; pw near 0 gives a narrow spike.
    """
    pw = max(0.05, min(0.95, pw))
    out = []
    for p in phases:
        s = 1.0 if p < pw else -1.0
        s += _poly_blep(p, dt)
        s -= _poly_blep((p + (1.0 - pw)) % 1.0, dt)
        out.append(s)
    return out


def gen_noise(n: int, rng) -> list:
    """White noise — bypasses phase-based generation."""
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def accumulate_phases(start_phase: float, freq: float, sr: int, n: int) -> tuple:
    """Compute list of phase values and return (phases, end_phase)."""
    dt = freq / sr
    phases = []
    p = start_phase
    for _ in range(n):
        phases.append(p)
        p = (p + dt) % 1.0
    return phases, p


def accumulate_phases_fm(start_phase: float, freqs: list, sr: int) -> tuple:
    """Like accumulate_phases but with a per-sample frequency list (for LFO pitch mod)."""
    phases = []
    p = start_phase
    for f in freqs:
        phases.append(p)
        p = (p + f / sr) % 1.0
    return phases, p


def generate(waveform: str, phases: list, dt: float, pw: float, rng) -> list:
    """Dispatch to the correct waveform generator."""
    if waveform == 'sine':
        return gen_sine(phases)
    elif waveform == 'sawtooth':
        return gen_sawtooth(phases, dt)
    elif waveform == 'rsaw':
        return gen_rsaw(phases, dt)
    elif waveform == 'square':
        return gen_square(phases, dt)
    elif waveform == 'triangle':
        return gen_triangle(phases)
    elif waveform == 'pulse':
        return gen_pulse(phases, dt, pw)
    elif waveform == 'noise':
        return gen_noise(len(phases), rng)
    else:
        raise ValueError(f"Unknown waveform: {waveform!r}")
