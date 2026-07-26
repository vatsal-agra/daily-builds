"""`faraday demo`: a self-checking, printed end-to-end walkthrough that
exercises every feature against an analytic oracle and exits non-zero if
anything is out of tolerance. This is the same content demo.sh drives from
the shell; it's implemented here so `python3 -m faraday.cli demo` and
`./demo.sh` can't drift apart."""

import math
import sys

from . import ac, circuits, dc, netlist, transient
from .elements import Diode
from .mna import Circuit

_PASS = 0
_FAIL = 0


def _check(label, ok, detail=""):
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        print(f"  [PASS] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def _close(a, b, rel=1e-3, abs_tol=1e-9):
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def demo_dc():
    print("\n== DC: voltage divider + multi-node mesh ==")
    c = circuits.voltage_divider(10, 1000, 1000)
    v, i = dc.operating_point(c)
    _check("V(2) == V*R2/(R1+R2)", _close(v["2"], 5.0), f"got {v['2']}")

    c2 = circuits.resistor_bridge(v=9.0, r=1000.0)
    v2, i2 = dc.operating_point(c2)
    # Kirchhoff's Current Law: sum of currents into every non-source node ~ 0
    kcl_ok = True
    for node in ("2", "3"):
        total = 0.0
        for e in c2.elements:
            if hasattr(e, "resistance"):
                if e.n1 == node:
                    total += (v2[e.n2] - v2[node]) / e.resistance
                elif e.n2 == node:
                    total += (v2[e.n1] - v2[node]) / e.resistance
        kcl_ok &= abs(total) < 1e-9
    _check("KCL holds at every internal node of a 5-resistor mesh", kcl_ok)


def demo_transient():
    print("\n== Transient: RC charge, RL current rise (vs closed form) ==")
    c = circuits.rc_step(5.0, 1000.0, 1e-6)
    res = transient.simulate(c, t_stop=5e-3, dt=1e-6, use_ic=True)
    RC = 1000.0 * 1e-6
    worst = max(abs(res.voltages["2"][i] - 5.0 * (1 - math.exp(-t / RC)))
                for i, t in enumerate(res.times))
    _check("RC step matches V*(1-exp(-t/RC)) within 5mV", worst < 5e-3, f"worst err {worst}")

    c2 = circuits.rl_step(5.0, 100.0, 0.1)
    res2 = transient.simulate(c2, t_stop=5e-3, dt=1e-6, use_ic=True)
    tau = 0.1 / 100.0
    worst2 = max(abs(res2.currents["L1"][i] - (5.0 / 100.0) * (1 - math.exp(-t / tau)))
                 for i, t in enumerate(res2.times))
    _check("RL step matches I*(1-exp(-tR/L)) within 0.1mA", worst2 < 1e-4, f"worst err {worst2}")


def demo_diode():
    print("\n== Nonlinear: Newton-Raphson diode / half-wave rectifier ==")
    c = circuits.half_wave_rectifier(v_amp=10.0, freq=60.0, r=1000.0)
    res = transient.simulate(c, t_stop=2 / 60, dt=1e-5)
    vmax, vmin = max(res.voltages["out"]), min(res.voltages["out"])
    _check("positive half-cycle passes through (~ Vamp - diode drop)",
           9.0 < vmax < 10.0, f"vmax={vmax}")
    _check("negative half-cycle is clipped near 0V", -0.05 < vmin < 0.01, f"vmin={vmin}")

    try:
        Diode("Dbad", "a", "b", Is=0)
        _check("Diode(Is=0) is rejected", False, "no exception raised")
    except ValueError:
        _check("Diode(Is=0) is rejected", True)


def demo_ac():
    print("\n== AC: RC cutoff frequency + RLC resonance ==")
    r, cap = 1000.0, 100e-9
    fc = 1 / (2 * math.pi * r * cap)
    circuit = circuits.rc_lowpass(1.0, r, cap)
    at_fc = ac.sweep(circuit, fc, fc, 1)
    mag = at_fc.magnitude("out")[0]
    _check("|H(f_c)| == 1/sqrt(2) at the analytic cutoff", _close(mag, 0.70710678, rel=1e-3),
           f"got {mag}")

    l, cres = 1e-3, 1e-6
    f0 = 1 / (2 * math.pi * math.sqrt(l * cres))
    rlc = circuits.rlc_series(v=5.0, r=10.0, l=l, c=cres, ac_mag=1.0)
    sweep_result = ac.sweep(rlc, f0 / 20, f0 * 20, 300)
    branch_currents = [abs(i) for i in sweep_result.currents["V1"]]
    peak_idx = max(range(len(branch_currents)), key=lambda i: branch_currents[i])
    peak_f = sweep_result.freqs[peak_idx]
    _check("series RLC current peaks at f0=1/(2*pi*sqrt(LC)) within 2%",
           _close(peak_f, f0, rel=0.02), f"peak at {peak_f}, expected {f0}")


def demo_opamp():
    print("\n== Ideal op-amp: inverting / non-inverting gain ==")
    inv = circuits.inverting_amplifier(v_amp=1.0, r_in=1000.0, r_f=10000.0)
    sweep_inv = ac.sweep(inv, 1000, 1000, 1)
    gain_inv = sweep_inv.voltages["out"][0] / sweep_inv.voltages["in"][0]
    _check("inverting amp gain == -Rf/Rin", _close(gain_inv, -10.0), f"got {gain_inv}")

    noninv = circuits.noninverting_amplifier(v_amp=1.0, r_in=1000.0, r_f=10000.0)
    sweep_noninv = ac.sweep(noninv, 1000, 1000, 1)
    gain_noninv = sweep_noninv.voltages["out"][0] / sweep_noninv.voltages["in"][0]
    _check("non-inverting amp gain == 1+Rf/Rin", _close(gain_noninv, 11.0), f"got {gain_noninv}")


def demo_netlist():
    print("\n== Netlist import/export round-trip ==")
    for name, factory in circuits.PRESETS.items():
        original = factory()
        text = netlist.to_netlist(original.elements, title=name)
        elements2, _ = netlist.parse_netlist(text)
        reimported = Circuit(elements2, name=name)
        v1, _ = dc.operating_point(original)
        v2, _ = dc.operating_point(reimported)
        same = all(_close(v1[n], v2[n], abs_tol=1e-6) for n in v1)
        _check(f"{name}: netlist round-trip reproduces identical DC solution", same)

    try:
        netlist.parse_netlist("R1 1 2 -100")
        _check("negative resistor value is rejected", False, "no exception raised")
    except ValueError:
        _check("negative resistor value is rejected", True)


def demo_error_handling():
    print("\n== Error handling: clean messages, no raw tracebacks ==")
    try:
        transient.simulate(circuits.rc_step(), t_stop=1e-9, dt=1e-6)
        _check("dt > t_stop is rejected", False, "no exception raised")
    except ValueError:
        _check("dt > t_stop is rejected", True)

    try:
        ac.sweep(circuits.rc_lowpass(), 0, 100, 5)
        _check("0 Hz AC sweep is rejected", False, "no exception raised")
    except ValueError:
        _check("0 Hz AC sweep is rejected", True)

    import json
    result = ac.sweep(circuits.rc_lowpass(), 1, 1e6, 5)
    encoded = json.dumps({"m": result.magnitude_db("0")})  # ground node: always 0V
    _check("AC magnitude_db(ground) never serializes to invalid JSON -Infinity",
           "-Infinity" not in encoded and "Infinity" not in encoded, encoded)


def run():
    print("Faraday end-to-end demo — every feature checked against an analytic oracle")
    demo_dc()
    demo_transient()
    demo_diode()
    demo_ac()
    demo_opamp()
    demo_netlist()
    demo_error_handling()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAIL:
        sys.exit(1)
