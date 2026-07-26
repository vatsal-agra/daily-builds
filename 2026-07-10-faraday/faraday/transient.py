"""Time-domain transient analysis via backward-Euler companion models.

Each timestep, capacitors/inductors are replaced by their backward-Euler
companion (a conductance/impedance plus a current/voltage term derived from
the *previous* timestep's state — see mna.py's docstring for the derivation)
and the resulting linear (or, with diodes, Newton-linearized) system is
solved exactly like a DC operating point. The companion's "previous state"
then advances to the just-solved value and the loop repeats.
"""

from dataclasses import dataclass, field

from .elements import Capacitor, Inductor, OpAmp, VSource, ISource
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
    voltages, snapshot_currents = dc.operating_point(snapshot_circuit)
    # snapshot_currents has one entry per branch-current unknown in the
    # *substitute* circuit — which includes a phantom entry named after
    # every substituted Capacitor (it became a VSource, and VSources always
    # carry a branch current). Rebuild `currents` from only the ORIGINAL
    # circuit's real branches instead of passing that dict through as-is:
    # otherwise a capacitor-named key would appear at t=0 with exactly one
    # sample and then vanish from every later timestep (Capacitors never
    # have a branch current once behind a real MNA companion model),
    # silently desyncing that series' length from `times` for the rest of
    # the run.
    currents = {}
    for e in circuit.elements:
        if isinstance(e, Inductor):
            currents[e.name] = e.ic  # ISource substitute -> not in snapshot_currents at all
        elif isinstance(e, (VSource, OpAmp)):  # real branches, untouched by substitution
            currents[e.name] = snapshot_currents[e.name]
    return voltages, currents, prev_state


def simulate(circuit, t_stop, dt, use_ic=False, max_iter=dc.MAX_ITER, tol=dc.TOL):
    if dt <= 0:
        raise ValueError("dt must be > 0")
    if t_stop < 0:
        raise ValueError("t_stop must be >= 0")
    if 0 < t_stop < dt:
        raise ValueError(f"dt ({dt:g}) is larger than t_stop ({t_stop:g}) — "
                          f"no timesteps would run; shrink dt or grow t_stop")

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
