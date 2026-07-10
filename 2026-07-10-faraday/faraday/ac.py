"""AC small-signal analysis: complex-phasor MNA sweep across frequency.

Reuses the exact same `mna.stamp` / `linalg.solve` code as DC and transient
analysis — capacitors/inductors are stamped as their complex admittance
(jωC) / impedance (jωL) directly, no companion-model bookkeeping needed
since there's no "previous timestep" in the frequency domain. Only the
elements' `ac_mag`/`ac_phase_deg` phasors drive the sweep; every other
independent source is implicitly zero, per the standard small-signal
convention (superposition — you're measuring the response to one AC
stimulus at a time, in the presence of everything else's linearized DC
bias).
"""

import cmath
import math
from dataclasses import dataclass, field

from . import mna


@dataclass
class ACResult:
    freqs: list = field(default_factory=list)
    voltages: dict = field(default_factory=dict)  # node -> [complex]
    currents: dict = field(default_factory=dict)  # branch -> [complex]

    def magnitude_db(self, node):
        # Floored at -300dB (a standard "digital silence" convention)
        # instead of computing log10(0) -> -inf, which is not valid JSON
        # and previously broke every AC/Bode request through the HTTP API
        # the instant a 0V node (e.g. ground, always present) was included.
        floor = 1e-15
        return [20 * math.log10(max(abs(v), floor)) for v in self.voltages[node]]

    def magnitude(self, node):
        return [abs(v) for v in self.voltages[node]]

    def phase_deg(self, node):
        return [math.degrees(cmath.phase(v)) for v in self.voltages[node]]


def sweep(circuit, f_start, f_stop, n_points=50, scale="log"):
    if f_start <= 0 or f_stop <= 0:
        raise ValueError("AC sweep frequencies must be > 0 Hz")
    if f_stop < f_start:
        raise ValueError("f_stop must be >= f_start")
    if n_points < 1:
        raise ValueError("n_points must be >= 1")

    if n_points == 1:
        freqs = [f_start]
    elif scale == "log":
        if f_start == 0:
            raise ValueError("log sweep requires f_start > 0")
        log_lo, log_hi = math.log10(f_start), math.log10(f_stop)
        freqs = [10 ** (log_lo + (log_hi - log_lo) * i / (n_points - 1))
                 for i in range(n_points)]
    elif scale == "linear":
        freqs = [f_start + (f_stop - f_start) * i / (n_points - 1)
                 for i in range(n_points)]
    else:
        raise ValueError(f"unknown scale {scale!r} (expected 'log' or 'linear')")

    result = ACResult()
    for f in freqs:
        omega = 2 * math.pi * f
        voltages, currents = mna.solve_linear(circuit, "ac", omega=omega)
        result.freqs.append(f)
        for n, v in voltages.items():
            result.voltages.setdefault(n, []).append(v)
        for name, i in currents.items():
            result.currents.setdefault(name, []).append(i)
    return result
