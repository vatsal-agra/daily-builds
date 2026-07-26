"""DC operating-point analysis, and the shared Newton-Raphson driver used by
both DC and transient solves whenever the circuit contains a nonlinear
element (currently: diodes)."""

from .elements import Diode
from . import mna, linalg

MAX_ITER = 200
TOL = 1e-9


class ConvergenceError(Exception):
    pass


def newton_solve(circuit, mode, t=0.0, h=None, prev_state=None,
                  max_iter=MAX_ITER, tol=TOL):
    """Solve one linear (or Newton-linearized nonlinear) MNA system.

    Returns (voltages, currents, diode_bias) where diode_bias is the
    converged per-diode Vd — callers doing transient analysis can seed the
    next timestep's Newton iteration with it for faster convergence.
    """
    diodes = [e for e in circuit.elements if isinstance(e, Diode)]
    diode_bias = {d.name: 0.0 for d in diodes}

    voltages = currents = None
    for _ in range(max_iter):
        A, z, _ = mna.stamp(circuit, mode, t=t, h=h, prev_state=prev_state,
                             diode_bias=diode_bias)
        try:
            x = linalg.solve(A, z)
        except linalg.SingularMatrixError as exc:
            raise linalg.SingularMatrixError(
                f"{circuit.name}: {exc} (every node needs a DC path to "
                f"ground, and there must be no loop of two independent "
                f"voltage sources)"
            ) from exc
        voltages, currents = circuit.unpack(x)

        if not diodes:
            return voltages, currents, diode_bias

        worst = 0.0
        new_bias = {}
        for d in diodes:
            v_new_raw = voltages[d.n_pos] - voltages[d.n_neg]
            v_new = d.limit_voltage(v_new_raw, diode_bias[d.name])
            worst = max(worst, abs(v_new - diode_bias[d.name]))
            new_bias[d.name] = v_new
        diode_bias = new_bias
        if worst < tol:
            return voltages, currents, diode_bias

    raise ConvergenceError(
        f"{circuit.name}: Newton-Raphson did not converge in {max_iter} "
        f"iterations (largest diode voltage step was still {worst:.3g}V)"
    )


def operating_point(circuit, t=0.0, max_iter=MAX_ITER, tol=TOL):
    """DC operating point: capacitors open, inductors shorted."""
    voltages, currents, diode_bias = newton_solve(
        circuit, "dc", t=t, max_iter=max_iter, tol=tol)
    return voltages, currents
