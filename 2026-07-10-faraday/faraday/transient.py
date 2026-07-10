"""Time-domain transient analysis via backward-Euler companion models.

Each timestep, capacitors/inductors are replaced by their backward-Euler
companion (a conductance/impedance plus a current/voltage term derived from
the *previous* timestep's state — see mna.py's docstring for the derivation)
and the resulting linear (or, with diodes, Newton-linearized) system is
solved exactly like a DC operating point. The companion's "previous state"
then advances to the just-solved value and the loop repeats.
"""

from dataclasses import dataclass, field

from .elements import Capacitor, Inductor, VSource, ISource
from . import dc, mna


@dataclass
class TransientResult:
    times: list = field(default_factory=list)
    voltages: dict = field(default_factory=dict)  # node -> [values]
    currents: dict = field(default_factory=dict)  # branch -> [values]

    def _append(self, t, voltages, currents):
        self.times.append(t)
        for n, v in voltages.items():
            self.voltages.setdefault(n, []).append(v)
        for name, i in currents.items():
            self.currents.setdefault(name, []).append(i)


def _initial_state(circuit, use_ic):
    """Return (t0 voltages, t0 currents, prev_state) for the first sample.

    Default (use_ic=False): a real DC operating point (capacitors open,
    inductors shorted) — the physically correct steady-state starting
    point, same as every SPICE simulator's default.

    use_ic=True: instantaneously, "held at a fixed voltage" *is* a voltage
    source and "held at a fixed current" *is* a current source, so we swap
    in substitute sources for exactly this one solve to get a t=0 snapshot
    consistent with the requested initial conditions.
    """
    if not use_ic:
        voltages, currents = dc.operating_point(circuit)
        prev_state = {}
        for e in circuit.elements:
            if isinstance(e, Capacitor):
                prev_state[e.name] = voltages[e.n1] - voltages[e.n2]
            elif isinstance(e, Inductor):
                prev_state[e.name] = currents[e.name]
        return voltages, currents, prev_state

    substitutes = []
    prev_state = {}
    for e in circuit.elements:
        if isinstance(e, Capacitor):
            substitutes.append(VSource.dc(e.name, e.n1, e.n2, e.ic))
            prev_state[e.name] = e.ic
        elif isinstance(e, Inductor):
            substitutes.append(ISource.dc(e.name, e.n1, e.n2, e.ic))
            prev_state[e.name] = e.ic
        else:
            substitutes.append(e)
    snapshot_circuit = mna.Circuit(substitutes, name=circuit.name + " (t=0 IC)")
    voltages, currents = dc.operating_point(snapshot_circuit)
    # Inductor "currents" from the snapshot came from an ISource stamp
    # (not a branch unknown), so they aren't in `currents` — but we
    # already know them: they're exactly the requested ic.
    for e in circuit.elements:
        if isinstance(e, Inductor):
            currents[e.name] = e.ic
    return voltages, currents, prev_state


def simulate(circuit, t_stop, dt, use_ic=False, max_iter=dc.MAX_ITER, tol=dc.TOL):
    if dt <= 0:
        raise ValueError("dt must be > 0")
    if t_stop < 0:
        raise ValueError("t_stop must be >= 0")

    result = TransientResult()
    voltages, currents, prev_state = _initial_state(circuit, use_ic)
    result._append(0.0, voltages, currents)

    n_steps = round(t_stop / dt)
    t = 0.0
    for _ in range(n_steps):
        t += dt
        voltages, currents, diode_bias = dc.newton_solve(
            circuit, "transient", t=t, h=dt, prev_state=prev_state,
            max_iter=max_iter, tol=tol)
        new_state = {}
        for e in circuit.elements:
            if isinstance(e, Capacitor):
                new_state[e.name] = voltages[e.n1] - voltages[e.n2]
            elif isinstance(e, Inductor):
                new_state[e.name] = currents[e.name]
        prev_state = new_state
        result._append(t, voltages, currents)

    return result
