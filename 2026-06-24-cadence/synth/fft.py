"""Cooley-Tukey radix-2 decimation-in-time FFT, from scratch.

Operates on lists of complex numbers (Python's built-in complex type).
The iterative bit-reversal + butterfly implementation avoids Python's
recursion limit for large transforms.
"""

import cmath
import math


def _bit_reverse(n: int) -> list:
    """Return the bit-reversal permutation for n (must be power of 2)."""
    bits = int(math.log2(n))
    perm = list(range(n))
    for i in range(n):
        rev = int(bin(i)[2:].zfill(bits)[::-1], 2)
        perm[i] = rev
    return perm


def fft(x: list) -> list:
    """Compute the FFT of a real or complex list. Length must be a power of 2."""
    n = len(x)
    if n == 0:
        return []
    if n & (n - 1):
        # Pad to next power of 2
        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 <<= 1
        x = list(x) + [0.0] * (next_pow2 - n)
        n = next_pow2

    # Bit-reversal permutation
    perm = _bit_reverse(n)
    a = [complex(x[perm[i]]) for i in range(n)]

    # Cooley-Tukey iterative butterfly
    half = n >> 1
    length = 2
    while length <= n:
        half_len = length >> 1
        w = cmath.exp(-2j * cmath.pi / length)
        for i in range(0, n, length):
            wn = complex(1.0, 0.0)
            for j in range(half_len):
                u = a[i + j]
                v = a[i + j + half_len] * wn
                a[i + j] = u + v
                a[i + j + half_len] = u - v
                wn *= w
        length <<= 1

    return a


def magnitude_spectrum(signal: list, window: bool = True) -> list:
    """Compute the one-sided magnitude spectrum of a real signal.

    Returns a list of (frequency_hz, magnitude) pairs for
    frequencies from 0 to sr/2.
    Uses a Hanning window to reduce spectral leakage.
    """
    n = len(signal)
    if window:
        win = [0.5 * (1.0 - math.cos(2.0 * math.pi * i / (n - 1)))
               for i in range(n)]
        signal = [signal[i] * win[i] for i in range(n)]

    spectrum = fft(signal)
    # One-sided: only indices 0..n//2
    half = n // 2 + 1
    # Normalize: divide by n, multiply by 2 for all bins except DC and Nyquist
    mags = []
    for k in range(half):
        mag = abs(spectrum[k]) / n
        if 0 < k < half - 1:
            mag *= 2.0
        mags.append(mag)
    return mags


def spectrum_bands(signal: list, sr: int, n_bins: int = 256,
                   f_min: float = 20.0, f_max: float = 8000.0) -> list:
    """Return n_bins log-spaced (freq, magnitude) pairs for visualization.

    The raw FFT bins are averaged into log-spaced bands.
    """
    # Use up to 4096 samples for the FFT
    chunk = signal[:4096] if len(signal) >= 4096 else signal
    mags = magnitude_spectrum(chunk)
    n_fft = (len(chunk) if not (len(chunk) & (len(chunk) - 1))
             else 2 ** (len(chunk) - 1).bit_length())
    freq_per_bin = sr / n_fft

    # Log-spaced frequency edges
    log_min = math.log10(max(f_min, 1.0))
    log_max = math.log10(f_max)
    bands = []
    for i in range(n_bins):
        f_lo = 10.0 ** (log_min + (log_max - log_min) * i / n_bins)
        f_hi = 10.0 ** (log_min + (log_max - log_min) * (i + 1) / n_bins)
        f_center = (f_lo + f_hi) / 2.0
        k_lo = int(f_lo / freq_per_bin)
        k_hi = max(int(f_hi / freq_per_bin), k_lo + 1)
        k_lo = max(0, min(k_lo, len(mags) - 1))
        k_hi = max(0, min(k_hi, len(mags)))
        if k_hi > k_lo:
            avg = sum(mags[k_lo:k_hi]) / (k_hi - k_lo)
        else:
            avg = mags[k_lo] if k_lo < len(mags) else 0.0
        bands.append((f_center, avg))

    return bands
