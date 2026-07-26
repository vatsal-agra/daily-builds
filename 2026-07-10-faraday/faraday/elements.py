"""Circuit element definitions.

Node names are strings; ``"0"`` is always ground and never appears as an
unknown in the MNA matrix. Elements are plain dataclasses — all the actual
stamping math lives in ``mna.py`` so there is exactly one place that knows
how a device turns into matrix entries, whether that's for DC, transient,
or AC analysis.

Sign/reference conventions (kept consistent everywhere):
  * Two-terminal passive/branch elements (R, C, L, V, Diode) are given as
    ``(n_pos, n_neg)``. Voltage is defined V(n_pos) - V(n_neg).
  * A branch current ``i`` (used for V sources and inductors) is defined
    flowing *into* the element at n_pos and out at n_neg.
  * An ``ISource`` injects ``value`` amps into the circuit at n_pos and
    draws them back out at n_neg (i.e. it looks like an arrow from n_neg to
    n_pos through the external circuit).
"""

from dataclasses import dataclass, field
import math


@dataclass
class Resistor:
    name: str
    n1: str
    n2: str
    resistance: float

    def __post_init__(self):
        if self.resistance <= 0:
            raise ValueError(f"{self.name}: resistance must be > 0")


@dataclass
class Capacitor:
    name: str
    n1: str
    n2: str
    capacitance: float
    ic: float = 0.0  # initial voltage V(n1)-V(n2) at t=0

    def __post_init__(self):
        if self.capacitance <= 0:
            raise ValueError(f"{self.name}: capacitance must be > 0")


@dataclass
class Inductor:
    name: str
    n1: str
    n2: str
    inductance: float
    ic: float = 0.0  # initial branch current at t=0

    def __post_init__(self):
        if self.inductance <= 0:
            raise ValueError(f"{self.name}: inductance must be > 0")


def _pulse(v1, v2, delay, rise, fall, width, period):
    def f(t):
        if t < delay:
            return v1
        tp = (t - delay) % period if period > 0 else (t - delay)
        if tp < rise:
            return v1 + (v2 - v1) * (tp / rise if rise > 0 else 1.0)
        tp -= rise
        if tp < width:
            return v2
        tp -= width
        if tp < fall:
            return v2 + (v1 - v2) * (tp / fall if fall > 0 else 1.0)
        return v1
    return f


def _sine(offset, amplitude, freq, delay=0.0, damping=0.0):
    def f(t):
        if t < delay:
            return offset
        dt = t - delay
        env = math.exp(-damping * dt) if damping else 1.0
        return offset + amplitude * env * math.sin(2 * math.pi * freq * dt)
    return f


@dataclass
class VSource:
    """Independent voltage source. ``waveform(t)`` gives the time-domain
    value for transient analysis; ``dc_value`` is used for DC operating
    point; ``ac_mag``/``ac_phase_deg`` give the small-signal phasor used
    only during AC sweeps (all other independent sources are zeroed, per
    the usual AC small-signal convention). ``spec`` is a serializable
    description of the waveform — ``("DC", (value,))``, ``("PULSE",
    (v1,v2,delay,rise,fall,width,period))``, or ``("SIN", (offset,
    amplitude,freq,delay,damping))`` — used by netlist.to_netlist() so a
    PULSE/SIN source round-trips through export/import instead of the
    waveform closure (which can't be serialized) silently getting dropped
    down to its DC value."""
    name: str
    n_pos: str
    n_neg: str
    dc_value: float = 0.0
    waveform: object = None  # callable t -> volts, or None to use dc_value
    ac_mag: float = 0.0
    ac_phase_deg: float = 0.0
    spec: tuple = None

    def __post_init__(self):
        if self.spec is None:
            self.spec = ("DC", (self.dc_value,))

    def value_at(self, t):
        return self.dc_value if self.waveform is None else self.waveform(t)

    def ac_phasor(self):
        phase = math.radians(self.ac_phase_deg)
        return self.ac_mag * complex(math.cos(phase), math.sin(phase))

    @staticmethod
    def dc(name, n_pos, n_neg, value):
        return VSource(name, n_pos, n_neg, dc_value=value, spec=("DC", (value,)))

    @staticmethod
    def pulse(name, n_pos, n_neg, v1, v2, delay, rise, fall, width, period):
        return VSource(name, n_pos, n_neg, dc_value=v1,
                        waveform=_pulse(v1, v2, delay, rise, fall, width, period),
                        spec=("PULSE", (v1, v2, delay, rise, fall, width, period)))

    @staticmethod
    def sine(name, n_pos, n_neg, offset, amplitude, freq, delay=0.0, damping=0.0):
        return VSource(name, n_pos, n_neg, dc_value=offset,
                        waveform=_sine(offset, amplitude, freq, delay, damping),
                        spec=("SIN", (offset, amplitude, freq, delay, damping)))


@dataclass
class ISource:
    name: str
    n_pos: str
    n_neg: str
    dc_value: float = 0.0
    waveform: object = None
    ac_mag: float = 0.0
    ac_phase_deg: float = 0.0
    spec: tuple = None

    def __post_init__(self):
        if self.spec is None:
            self.spec = ("DC", (self.dc_value,))

    def value_at(self, t):
        return self.dc_value if self.waveform is None else self.waveform(t)

    def ac_phasor(self):
        phase = math.radians(self.ac_phase_deg)
        return self.ac_mag * complex(math.cos(phase), math.sin(phase))

    @staticmethod
    def dc(name, n_pos, n_neg, value):
        return ISource(name, n_pos, n_neg, dc_value=value, spec=("DC", (value,)))


@dataclass
class Diode:
    """Shockley-equation diode: Id = Is * (exp(Vd / (n*Vt)) - 1)."""
    name: str
    n_pos: str  # anode
    n_neg: str  # cathode
    Is: float = 1e-14
    n: float = 1.0
    Vt: float = 0.025852  # thermal voltage at ~300K

    def __post_init__(self):
        if self.Is <= 0:
            raise ValueError(f"{self.name}: Is (saturation current) must be > 0")
        if self.n <= 0:
            raise ValueError(f"{self.name}: n (ideality factor) must be > 0")
        if self.Vt <= 0:
            raise ValueError(f"{self.name}: Vt (thermal voltage) must be > 0")

    @property
    def nVt(self):
        return self.n * self.Vt

    def current(self, vd):
        return self.Is * (math.exp(vd / self.nVt) - 1.0)

    def conductance(self, vd):
        return (self.Is / self.nVt) * math.exp(vd / self.nVt)

    def critical_voltage(self):
        return self.nVt * math.log(self.nVt / (math.sqrt(2) * self.Is))

    def limit_voltage(self, v_new, v_old):
        """SPICE-style exponential damping so Newton-Raphson can't fling
        the guess into an exp() blow-up / divergence loop."""
        vt = self.nVt
        vcrit = self.critical_voltage()
        if v_new > vcrit and abs(v_new - v_old) > 2 * vt:
            if v_old > 0:
                arg = 1 + (v_new - v_old) / vt
                v_new = v_old + vt * math.log(arg) if arg > 0 else vcrit
            else:
                v_new = vt * math.log(v_new / vt) if v_new > 0 else vcrit
        return v_new


@dataclass
class OpAmp:
    """Ideal op-amp (infinite gain, infinite input impedance, zero output
    impedance) via a nullor stamp: the extra unknown is the current the
    op-amp sources into n_out, and the extra constraint equation enforces
    the virtual short V(n_plus) == V(n_minus)."""
    name: str
    n_plus: str
    n_minus: str
    n_out: str
