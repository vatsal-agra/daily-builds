"""A small library of preset circuits — used by the CLI (`faraday demo`),
the interactive UI's "load preset" menu, and the test suite's analytic
oracles."""

from .elements import Resistor, Capacitor, Inductor, VSource, ISource, Diode, OpAmp
from .mna import Circuit


def voltage_divider(v=10.0, r1=1000.0, r2=1000.0):
    """V1 -- R1 -- (node 2) -- R2 -- GND. Analytic: V(2) = V1*R2/(R1+R2)."""
    return Circuit([
        VSource.dc("V1", "1", "0", v),
        Resistor("R1", "1", "2", r1),
        Resistor("R2", "2", "0", r2),
    ], name="voltage_divider")


def resistor_bridge(v=9.0, r=1000.0):
    """A small multi-node resistor mesh (5 unknowns) — used to test the
    general MNA solve (not just a 1-D divider) against Kirchhoff's laws."""
    return Circuit([
        VSource.dc("V1", "1", "0", v),
        Resistor("R1", "1", "2", r),
        Resistor("R2", "1", "3", r * 2),
        Resistor("R3", "2", "3", r * 3),
        Resistor("R4", "2", "0", r),
        Resistor("R5", "3", "0", r * 1.5),
    ], name="resistor_bridge")


def rc_step(v=5.0, r=1000.0, c=1e-6):
    """Step voltage source charging a capacitor through a resistor.
    Analytic: Vc(t) = V*(1 - exp(-t/RC))."""
    return Circuit([
        VSource.dc("V1", "1", "0", v),
        Resistor("R1", "1", "2", r),
        Capacitor("C1", "2", "0", c),
    ], name="rc_step")


def rl_step(v=5.0, r=100.0, l=0.1):
    """Step voltage source driving current up through a series R-L.
    Analytic: I(t) = (V/R)*(1 - exp(-t*R/L))."""
    return Circuit([
        VSource.dc("V1", "1", "0", v),
        Resistor("R1", "1", "2", r),
        Inductor("L1", "2", "0", l),
    ], name="rl_step")


def rlc_series(v=5.0, r=10.0, l=1e-3, c=1e-6, ac_mag=1.0):
    """Series RLC — resonant at f0 = 1/(2*pi*sqrt(LC)). ac_mag drives the
    AC sweep; the DC value drives transient ringing."""
    return Circuit([
        VSource("V1", "1", "0", dc_value=v, ac_mag=ac_mag),
        Resistor("R1", "1", "2", r),
        Inductor("L1", "2", "3", l),
        Capacitor("C1", "3", "0", c),
    ], name="rlc_series")


def rc_lowpass(v_ac=1.0, r=1000.0, c=100e-9):
    """RC low-pass filter for a Bode sweep. Analytic cutoff:
    f_c = 1/(2*pi*R*C), -3dB / -45 degrees there."""
    return Circuit([
        VSource("V1", "in", "0", dc_value=0.0, ac_mag=v_ac),
        Resistor("R1", "in", "out", r),
        Capacitor("C1", "out", "0", c),
    ], name="rc_lowpass")


def half_wave_rectifier(v_amp=10.0, freq=60.0, r=1000.0):
    """Sinusoidal source -> diode -> load resistor: classic half-wave
    rectifier, output should track the input on positive half-cycles and
    stay near 0 (a diode drop below 0) on negative half-cycles."""
    return Circuit([
        VSource.sine("V1", "in", "0", offset=0.0, amplitude=v_amp, freq=freq),
        Diode("D1", "in", "out"),
        Resistor("R1", "out", "0", r),
    ], name="half_wave_rectifier")


def inverting_amplifier(v_amp=1.0, freq=1000.0, r_in=1000.0, r_f=10000.0):
    """Ideal-op-amp inverting amplifier. Analytic gain: -Rf/Rin."""
    return Circuit([
        VSource("V1", "in", "0", dc_value=0.0, ac_mag=v_amp),
        Resistor("Rin", "in", "vminus", r_in),
        Resistor("Rf", "vminus", "out", r_f),
        OpAmp("O1", "0", "vminus", "out"),
    ], name="inverting_amplifier")


def noninverting_amplifier(v_amp=1.0, freq=1000.0, r_in=1000.0, r_f=10000.0):
    """Ideal-op-amp non-inverting amplifier. Analytic gain: 1 + Rf/Rin."""
    return Circuit([
        VSource("V1", "in", "0", dc_value=0.0, ac_mag=v_amp),
        Resistor("Rin", "vminus", "0", r_in),
        Resistor("Rf", "vminus", "out", r_f),
        OpAmp("O1", "in", "vminus", "out"),
    ], name="noninverting_amplifier")


PRESETS = {
    "voltage_divider": voltage_divider,
    "resistor_bridge": resistor_bridge,
    "rc_step": rc_step,
    "rl_step": rl_step,
    "rlc_series": rlc_series,
    "rc_lowpass": rc_lowpass,
    "half_wave_rectifier": half_wave_rectifier,
    "inverting_amplifier": inverting_amplifier,
    "noninverting_amplifier": noninverting_amplifier,
}
