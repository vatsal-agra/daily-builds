"""Modified Nodal Analysis: turns a list of circuit elements into the
matrix equation A x = z, where x is [node voltages..., branch currents...].

This module owns exactly two things: numbering the unknowns, and "stamping"
each element's contribution into A/z for a requested analysis mode. Every
other module (dc.py, transient.py, ac.py) just decides *what* to stamp
(which timestep, which frequency, which diode linearization point) and then
calls straight into this file to build and solve the system.
"""

from .elements import Resistor, Capacitor, Inductor, VSource, ISource, Diode, OpAmp
from . import linalg

GROUND = "0"

# Standard SPICE numerical regularization: a tiny conductance stamped in
# parallel with every nonlinear junction. Real diode conductance underflows
# to exact 0.0 at ordinary reverse-bias voltages (float64 exp() underflow
# starts well within plausible operating ranges), which can otherwise leave
# a node with no DC-connected path to ground and a singular MNA matrix.
GMIN = 1e-12


class Circuit:
    def __init__(self, elements, name="circuit"):
        self.name = name
        self.elements = list(elements)
        self._number_unknowns()

    def _number_unknowns(self):
        # Name-specific duplicate check first, so "two op-amps both named
        # O1" reports the actual offending name instead of the generic
        # "duplicate names among V/L/OpAmp branches" check below.
        by_name = {}
        for e in self.elements:
            if e.name in by_name and by_name[e.name] is not e:
                raise ValueError(f"duplicate element name {e.name!r}")
            by_name[e.name] = e
        self.by_name = by_name

        node_names = []
        seen = set()
        for e in self.elements:
            for attr in ("n1", "n2", "n_pos", "n_neg", "n_plus", "n_minus", "n_out"):
                n = getattr(e, attr, None)
                if n is not None and n != GROUND and n not in seen:
                    seen.add(n)
                    node_names.append(n)
        node_names.sort()
        self.node_names = node_names
        self.node_index = {n: i for i, n in enumerate(node_names)}
        self.n_nodes = len(node_names)

        extra = []
        for e in self.elements:
            if isinstance(e, (VSource, Inductor, OpAmp)):
                extra.append(e.name)
        if len(extra) != len(set(extra)):
            raise ValueError("duplicate element names among V/L/OpAmp branches")
        self.extra_index = {name: self.n_nodes + i for i, name in enumerate(extra)}
        self.size = self.n_nodes + len(extra)

    def vidx(self, node):
        """Row/col index for a node's voltage unknown, or None for ground."""
        if node == GROUND:
            return None
        if node not in self.node_index:
            raise ValueError(f"unknown node {node!r} — not attached to any element")
        return self.node_index[node]

    def zero_system(self, complex_valued=False):
        z0 = 0j if complex_valued else 0.0
        A = [[z0] * self.size for _ in range(self.size)]
        b = [z0] * self.size
        return A, b

    def unpack(self, x):
        """Split a solved unknown vector into {node: voltage} and
        {branch_name: current}."""
        voltages = {GROUND: 0.0}
        for n, i in self.node_index.items():
            voltages[n] = x[i]
        currents = {name: x[i] for name, i in self.extra_index.items()}
        return voltages, currents


def _stamp_conductance(A, i1, i2, g):
    if i1 is not None:
        A[i1][i1] += g
    if i2 is not None:
        A[i2][i2] += g
    if i1 is not None and i2 is not None:
        A[i1][i2] -= g
        A[i2][i1] -= g


def _stamp_branch(A, b, ip, ineg, k, rhs_coeff_p=1, rhs_coeff_n=-1):
    """Wire branch-current unknown k into the KCL rows of its two nodes."""
    if ip is not None:
        A[ip][k] += 1
        A[k][ip] += rhs_coeff_p
    if ineg is not None:
        A[ineg][k] -= 1
        A[k][ineg] += rhs_coeff_n


def stamp(circuit, mode, t=0.0, h=None, omega=None, prev_state=None, diode_bias=None):
    """Build (A, z) for the requested mode.

    mode: 'dc' | 'transient' | 'ac'
    h: timestep (required for 'transient')
    omega: angular frequency 2*pi*f (required for 'ac')
    prev_state: {element_name: previous companion value} for C (voltage)
                and L (current), required for 'transient'
    diode_bias: {element_name: Vd linearization point}; defaults to 0.0
    """
    complex_valued = mode == "ac"
    A, z = circuit.zero_system(complex_valued)
    prev_state = prev_state or {}
    diode_bias = diode_bias or {}
    diode_updates = {}

    for e in circuit.elements:
        if isinstance(e, Resistor):
            i1, i2 = circuit.vidx(e.n1), circuit.vidx(e.n2)
            _stamp_conductance(A, i1, i2, 1.0 / e.resistance)

        elif isinstance(e, Capacitor):
            i1, i2 = circuit.vidx(e.n1), circuit.vidx(e.n2)
            if mode == "dc":
                pass  # open circuit at DC operating point
            elif mode == "ac":
                _stamp_conductance(A, i1, i2, 1j * omega * e.capacitance)
            elif mode == "transient":
                geq = e.capacitance / h
                _stamp_conductance(A, i1, i2, geq)
                v_prev = prev_state.get(e.name, e.ic)
                ieq = geq * v_prev
                if i1 is not None:
                    z[i1] += ieq
                if i2 is not None:
                    z[i2] -= ieq
            else:
                raise ValueError(f"unknown mode {mode!r}")

        elif isinstance(e, Inductor):
            i1, i2 = circuit.vidx(e.n1), circuit.vidx(e.n2)
            k = circuit.extra_index[e.name]
            if mode == "dc":
                impedance, rhs = 0.0, 0.0
            elif mode == "ac":
                impedance, rhs = 1j * omega * e.inductance, 0.0
            elif mode == "transient":
                # backward Euler: v = zl*(i(t) - i_prev), zl = L/h, so the
                # branch row "V1 - V2 - zl*i(t) = rhs" needs rhs = -zl*i_prev.
                zl = e.inductance / h
                i_prev = prev_state.get(e.name, e.ic)
                impedance, rhs = zl, -zl * i_prev
            else:
                raise ValueError(f"unknown mode {mode!r}")
            if i1 is not None:
                A[i1][k] += 1
                A[k][i1] += 1
            if i2 is not None:
                A[i2][k] -= 1
                A[k][i2] -= 1
            A[k][k] += -impedance
            z[k] += rhs

        elif isinstance(e, VSource):
            i1, i2 = circuit.vidx(e.n_pos), circuit.vidx(e.n_neg)
            k = circuit.extra_index[e.name]
            if i1 is not None:
                A[i1][k] += 1
                A[k][i1] += 1
            if i2 is not None:
                A[i2][k] -= 1
                A[k][i2] -= 1
            z[k] += e.ac_phasor() if mode == "ac" else e.value_at(t)

        elif isinstance(e, ISource):
            i1, i2 = circuit.vidx(e.n_pos), circuit.vidx(e.n_neg)
            val = e.ac_phasor() if mode == "ac" else e.value_at(t)
            if i1 is not None:
                z[i1] += val
            if i2 is not None:
                z[i2] -= val

        elif isinstance(e, Diode):
            if mode == "ac":
                raise ValueError(
                    f"{e.name}: AC analysis of circuits containing diodes "
                    f"is not supported (would require linearizing around a "
                    f"DC bias point) — remove the diode or use dc/tran"
                )
            i1, i2 = circuit.vidx(e.n_pos), circuit.vidx(e.n_neg)
            vd = diode_bias.get(e.name, 0.0)
            gd = e.conductance(vd)
            id0 = e.current(vd)
            ieq = id0 - gd * vd
            diode_updates[e.name] = vd
            # GMIN is a literal extra parallel conductance (passes through
            # the origin), so it's stamped separately and never touches ieq.
            _stamp_conductance(A, i1, i2, gd + GMIN)
            if i1 is not None:
                z[i1] -= ieq
            if i2 is not None:
                z[i2] += ieq

        elif isinstance(e, OpAmp):
            i_plus, i_minus = circuit.vidx(e.n_plus), circuit.vidx(e.n_minus)
            i_out = circuit.vidx(e.n_out)
            k = circuit.extra_index[e.name]
            if i_out is not None:
                A[i_out][k] += 1
            if i_plus is not None:
                A[k][i_plus] += 1
            if i_minus is not None:
                A[k][i_minus] -= 1
            # z[k] stays 0: the constraint is V(n_plus) == V(n_minus)

        else:
            raise TypeError(f"unstampable element type: {type(e)!r}")  # pragma: no cover

    return A, z, diode_updates


def solve_linear(circuit, mode, **kwargs):
    A, z, _ = stamp(circuit, mode, **kwargs)
    try:
        x = linalg.solve(A, z)
    except linalg.SingularMatrixError as exc:
        raise linalg.SingularMatrixError(
            f"{circuit.name}: {exc} (every node needs a DC path to ground, "
            f"and there must be no loop of two independent voltage sources)"
        ) from exc
    return circuit.unpack(x)
