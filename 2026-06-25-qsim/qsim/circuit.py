"""
Circuit: a sequence of quantum operations (gates + measurements).

The Circuit object stores instructions as a list and executes them by
applying gates to a QuantumState.  Also provides barrier (for display),
reset, and classical control hooks.
"""

import random
from .state import QuantumState
from .gates import (
    Gate, GATES,
    apply_gate,
    Rx, Ry, Rz, Phase, U, controlled,
)
from .measure import (
    measure as _measure_all,
    measure_qubit as _measure_qubit,
    sample as _sample,
)


class Instruction:
    """One step in a circuit."""
    def __init__(self, kind: str, gate=None, qubits=None,
                 clbits=None, label: str = ""):
        self.kind = kind        # 'gate', 'measure', 'barrier', 'reset'
        self.gate = gate        # Gate object (for 'gate' instructions)
        self.qubits = qubits or []
        self.clbits = clbits or []
        self.label = label

    def __repr__(self):
        if self.kind == "gate":
            return f"{self.gate.name}({self.qubits})"
        return f"{self.kind}({self.qubits})"


class Circuit:
    """
    Quantum circuit builder and executor.

    Qubit indices 0..n-1 (qubit 0 = MSB in the state vector).
    Classical bits 0..m-1 store measurement results.
    """

    def __init__(self, n_qubits: int, n_clbits: int = 0, name: str = "circuit"):
        if n_qubits < 1:
            raise ValueError("Need at least 1 qubit")
        self.n = n_qubits
        self.m = n_clbits
        self.name = name
        self._instructions: list[Instruction] = []

    # ------------------------------------------------------------------
    # Single-qubit gates
    # ------------------------------------------------------------------

    def h(self, qubit: int) -> "Circuit":
        return self._gate(GATES["H"], [qubit])

    def x(self, qubit: int) -> "Circuit":
        return self._gate(GATES["X"], [qubit])

    def y(self, qubit: int) -> "Circuit":
        return self._gate(GATES["Y"], [qubit])

    def z(self, qubit: int) -> "Circuit":
        return self._gate(GATES["Z"], [qubit])

    def s(self, qubit: int) -> "Circuit":
        return self._gate(GATES["S"], [qubit])

    def sdg(self, qubit: int) -> "Circuit":
        return self._gate(GATES["Sdg"], [qubit])

    def t(self, qubit: int) -> "Circuit":
        return self._gate(GATES["T"], [qubit])

    def tdg(self, qubit: int) -> "Circuit":
        return self._gate(GATES["Tdg"], [qubit])

    def rx(self, theta: float, qubit: int) -> "Circuit":
        return self._gate(Rx(theta), [qubit])

    def ry(self, theta: float, qubit: int) -> "Circuit":
        return self._gate(Ry(theta), [qubit])

    def rz(self, theta: float, qubit: int) -> "Circuit":
        return self._gate(Rz(theta), [qubit])

    def p(self, theta: float, qubit: int) -> "Circuit":
        return self._gate(Phase(theta), [qubit])

    def u(self, theta: float, phi: float, lam: float, qubit: int) -> "Circuit":
        return self._gate(U(theta, phi, lam), [qubit])

    def i(self, qubit: int) -> "Circuit":
        return self._gate(GATES["I"], [qubit])

    # ------------------------------------------------------------------
    # Two-qubit gates
    # ------------------------------------------------------------------

    def cnot(self, control: int, target: int) -> "Circuit":
        return self._gate(GATES["CNOT"], [control, target])

    def cx(self, control: int, target: int) -> "Circuit":
        return self.cnot(control, target)

    def cz(self, qubit0: int, qubit1: int) -> "Circuit":
        return self._gate(GATES["CZ"], [qubit0, qubit1])

    def swap(self, qubit0: int, qubit1: int) -> "Circuit":
        return self._gate(GATES["SWAP"], [qubit0, qubit1])

    def iswap(self, qubit0: int, qubit1: int) -> "Circuit":
        return self._gate(GATES["iSWAP"], [qubit0, qubit1])

    def cp(self, theta: float, control: int, target: int) -> "Circuit":
        """Controlled-Phase gate."""
        return self._gate(controlled(Phase(theta)), [control, target])

    def crx(self, theta: float, control: int, target: int) -> "Circuit":
        return self._gate(controlled(Rx(theta)), [control, target])

    def cry(self, theta: float, control: int, target: int) -> "Circuit":
        return self._gate(controlled(Ry(theta)), [control, target])

    def crz(self, theta: float, control: int, target: int) -> "Circuit":
        return self._gate(controlled(Rz(theta)), [control, target])

    def cu(self, theta: float, phi: float, lam: float,
           control: int, target: int) -> "Circuit":
        return self._gate(controlled(U(theta, phi, lam)), [control, target])

    # ------------------------------------------------------------------
    # Three-qubit gates
    # ------------------------------------------------------------------

    def ccx(self, ctrl0: int, ctrl1: int, target: int) -> "Circuit":
        """Toffoli (CCX) gate."""
        return self._gate(GATES["Toffoli"], [ctrl0, ctrl1, target])

    def toffoli(self, ctrl0: int, ctrl1: int, target: int) -> "Circuit":
        return self.ccx(ctrl0, ctrl1, target)

    def fredkin(self, ctrl: int, tgt0: int, tgt1: int) -> "Circuit":
        """Fredkin (CSWAP) gate."""
        return self._gate(GATES["Fredkin"], [ctrl, tgt0, tgt1])

    def cswap(self, ctrl: int, tgt0: int, tgt1: int) -> "Circuit":
        return self.fredkin(ctrl, tgt0, tgt1)

    # ------------------------------------------------------------------
    # Custom gate
    # ------------------------------------------------------------------

    def gate(self, g: Gate, qubits: list) -> "Circuit":
        """Apply any Gate object to the given qubits."""
        return self._gate(g, qubits)

    # ------------------------------------------------------------------
    # Measurement & reset
    # ------------------------------------------------------------------

    def measure(self, qubit: int, clbit: int) -> "Circuit":
        """Measure qubit → clbit."""
        self._instructions.append(
            Instruction("measure", qubits=[qubit], clbits=[clbit])
        )
        return self

    def measure_all(self) -> "Circuit":
        """Measure all qubits → classical bits 0..n-1."""
        for q in range(self.n):
            self.measure(q, q)
        return self

    def reset(self, qubit: int) -> "Circuit":
        """Reset qubit to |0⟩."""
        self._instructions.append(
            Instruction("reset", qubits=[qubit])
        )
        return self

    def barrier(self, *qubits) -> "Circuit":
        """Visual barrier (no effect on simulation)."""
        self._instructions.append(
            Instruction("barrier", qubits=list(qubits) or list(range(self.n)))
        )
        return self

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, initial_state: QuantumState = None,
            shots: int = 1,
            rng: random.Random = None,
            noise_model=None) -> "CircuitResult":
        """
        Execute the circuit.

        Args:
          initial_state: Starting state (default: |0…0⟩).
          shots: Number of times to run (for sampling).  If > 1, the circuit
                 is re-run from scratch each shot and measurement results are
                 accumulated in a histogram.
          rng: Optional seeded random.Random for reproducibility.
          noise_model: Optional NoiseModel from noise.py.

        Returns: CircuitResult
        """
        if rng is None:
            rng = random.Random()

        if shots > 1:
            # Multi-shot: accumulate measurement histograms
            counts = {}
            final_states = []
            for _ in range(shots):
                state0 = (initial_state.copy() if initial_state
                          else QuantumState.zero(self.n))
                clbits = [0] * max(self.m, 1)
                state, cl = self._run_once(state0, clbits, rng, noise_model)
                key = "".join(str(b) for b in cl[:self.n]) if self.m else ""
                if key:
                    counts[key] = counts.get(key, 0) + 1
                final_states.append(state)
            return CircuitResult(
                final_state=final_states[-1],
                counts=counts,
                shots=shots,
                circuit=self,
            )
        else:
            state0 = (initial_state.copy() if initial_state
                      else QuantumState.zero(self.n))
            clbits = [0] * max(self.m, 1)
            state, cl = self._run_once(state0, clbits, rng, noise_model)
            return CircuitResult(
                final_state=state,
                counts={"".join(str(b) for b in cl[:self.n]): 1} if self.m else {},
                shots=1,
                circuit=self,
                classical_bits=cl,
            )

    def _run_once(self, state: QuantumState, clbits: list,
                  rng: random.Random, noise_model):
        """Execute one shot, modifying state in place."""
        for instr in self._instructions:
            if instr.kind == "gate":
                state = apply_gate(state, instr.gate, instr.qubits)
                if noise_model is not None:
                    state = noise_model.apply(state, instr, rng)
            elif instr.kind == "measure":
                q = instr.qubits[0]
                cb = instr.clbits[0]
                outcome, state = _measure_qubit(state, q, rng)
                if cb < len(clbits):
                    clbits[cb] = outcome
            elif instr.kind == "reset":
                q = instr.qubits[0]
                outcome, state = _measure_qubit(state, q, rng)
                if outcome == 1:
                    from .gates import apply_1q
                    state = apply_1q(state, GATES["X"], q)
            elif instr.kind == "barrier":
                pass  # no-op
        return state, clbits

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gate(self, g: Gate, qubits: list) -> "Circuit":
        for q in qubits:
            if not (0 <= q < self.n):
                raise ValueError(
                    f"Qubit {q} out of range for {self.n}-qubit circuit"
                )
        self._instructions.append(Instruction("gate", gate=g, qubits=qubits))
        return self

    def depth(self) -> int:
        """Longest gate path (counting only gate instructions)."""
        qubit_depth = [0] * self.n
        for instr in self._instructions:
            if instr.kind == "gate":
                d = max(qubit_depth[q] for q in instr.qubits) + 1
                for q in instr.qubits:
                    qubit_depth[q] = d
        return max(qubit_depth) if qubit_depth else 0

    def count_ops(self) -> dict:
        """Count gate operations by name."""
        counts = {}
        for instr in self._instructions:
            if instr.kind == "gate":
                counts[instr.gate.name] = counts.get(instr.gate.name, 0) + 1
        return counts

    def __len__(self) -> int:
        return sum(1 for i in self._instructions if i.kind == "gate")

    def __repr__(self) -> str:
        return (f"Circuit(n={self.n}, m={self.m}, "
                f"depth={self.depth()}, gates={len(self)})")


class CircuitResult:
    """Result of running a circuit."""

    def __init__(self, final_state: QuantumState, counts: dict,
                 shots: int, circuit: Circuit, classical_bits=None):
        self.final_state = final_state
        self.counts = counts          # {bitstring: count}
        self.shots = shots
        self.circuit = circuit
        self.classical_bits = classical_bits or []

    def most_likely(self) -> str:
        """Return the bitstring with the highest count."""
        if not self.counts:
            return ""
        return max(self.counts, key=lambda k: self.counts[k])

    def probabilities(self) -> dict:
        """Return estimated probabilities from shot counts."""
        if not self.counts or self.shots == 0:
            return {}
        return {k: v / self.shots for k, v in self.counts.items()}

    def __repr__(self) -> str:
        top = self.most_likely()
        return (f"CircuitResult(shots={self.shots}, "
                f"most_likely={top!r}, "
                f"outcomes={len(self.counts)})")
