"""Biquad IIR filter implementations.

Coefficients computed from the Audio EQ Cookbook (Robert Bristow-Johnson).
Filter state (x1, x2, y1, y2) is returned alongside output so callers can
chain notes without resetting state mid-phrase.
"""

import math

_TWO_PI = 2.0 * math.pi


# ---------------------------------------------------------------------------
# Coefficient calculators  (return b0, b1, b2, a1, a2 — normalized by a0)
# ---------------------------------------------------------------------------

def _norm(b0, b1, b2, a0, a1, a2):
    return b0/a0, b1/a0, b2/a0, a1/a0, a2/a0


def lpf_coeffs(cutoff: float, q: float, sr: int) -> tuple:
    """2nd-order Butterworth low-pass filter."""
    cutoff = min(max(cutoff, 20.0), sr * 0.499)
    q = max(q, 0.01)
    w0 = _TWO_PI * cutoff / sr
    alpha = math.sin(w0) / (2.0 * q)
    cosw = math.cos(w0)
    b1 = 1.0 - cosw
    b0 = b1 / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cosw
    a2 = 1.0 - alpha
    return _norm(b0, b1, b0, a0, a1, a2)


def hpf_coeffs(cutoff: float, q: float, sr: int) -> tuple:
    """2nd-order high-pass filter."""
    cutoff = min(max(cutoff, 20.0), sr * 0.499)
    q = max(q, 0.01)
    w0 = _TWO_PI * cutoff / sr
    alpha = math.sin(w0) / (2.0 * q)
    cosw = math.cos(w0)
    b1 = -(1.0 + cosw)
    b0 = -b1 / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cosw
    a2 = 1.0 - alpha
    return _norm(b0, b1, b0, a0, a1, a2)


def bpf_coeffs(cutoff: float, q: float, sr: int) -> tuple:
    """2nd-order band-pass filter (peak gain = 1)."""
    cutoff = min(max(cutoff, 20.0), sr * 0.499)
    q = max(q, 0.01)
    w0 = _TWO_PI * cutoff / sr
    alpha = math.sin(w0) / (2.0 * q)
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha
    return _norm(b0, b1, b2, a0, a1, a2)


def notch_coeffs(cutoff: float, q: float, sr: int) -> tuple:
    """2nd-order notch (band-reject) filter."""
    cutoff = min(max(cutoff, 20.0), sr * 0.499)
    q = max(q, 0.01)
    w0 = _TWO_PI * cutoff / sr
    alpha = math.sin(w0) / (2.0 * q)
    cosw = math.cos(w0)
    b0 = 1.0
    b1 = -2.0 * cosw
    b2 = 1.0
    a0 = 1.0 + alpha
    a1 = b1
    a2 = 1.0 - alpha
    return _norm(b0, b1, b2, a0, a1, a2)


def get_coeffs(filter_type: str, cutoff: float, q: float, sr: int) -> tuple:
    if filter_type == 'lpf':
        return lpf_coeffs(cutoff, q, sr)
    elif filter_type == 'hpf':
        return hpf_coeffs(cutoff, q, sr)
    elif filter_type == 'bpf':
        return bpf_coeffs(cutoff, q, sr)
    elif filter_type == 'notch':
        return notch_coeffs(cutoff, q, sr)
    elif filter_type == 'none':
        return 1.0, 0.0, 0.0, 0.0, 0.0
    else:
        raise ValueError(f"Unknown filter type: {filter_type!r}")


# ---------------------------------------------------------------------------
# Filter application
# ---------------------------------------------------------------------------

def apply_filter(samples: list, b0: float, b1: float, b2: float,
                 a1: float, a2: float,
                 state: tuple = None) -> tuple:
    """Apply biquad in Direct Form II Transposed.

    Returns (output_samples, new_state) where new_state = (x1, x2, y1, y2)
    so the filter can be continued across note boundaries.
    """
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


def apply_filter_block(samples: list, filter_type: str, cutoff: float,
                       q: float, sr: int, state: tuple = None) -> tuple:
    """Compute coefficients and apply filter. Convenience wrapper."""
    b0, b1, b2, a1, a2 = get_coeffs(filter_type, cutoff, q, sr)
    return apply_filter(samples, b0, b1, b2, a1, a2, state)
