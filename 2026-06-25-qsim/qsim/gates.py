"""
Gate library: standard quantum gates as complex 2×2 / 4×4 / 8×8 matrices,
plus efficient O(2^n) applicators that operate directly on state amplitudes.

Qubit ordering: qubit 0 is the MOST significant bit (index 0 = |0…0⟩).
"""

import cmath
import math
from .state import QuantumState

_I = 1j
_SQRT2_INV = 1.0 / math.sqrt(2)


class Gate:
    """Immutable gate descriptor: matrix + name + qubit count."""

    def __init__(self, name: str, matrix: list, n_qubits: int = 1):
        self.name = name
        self.matrix = matrix  # flat list of complex, row-major, (2^n)×(2^n)
        self.n_qubits = n_qubits
        self.dim = 1 << n_qubits
        assert len(matrix) == self.dim * self.dim, (
            f"{name}: expected {self.dim**2} elements, got {len(matrix)}"
        )

    def is_unitary(self, eps: float = 1e-9) -> bool:
        """Check U†U = I."""
        d = self.dim
        for i in range(d):
            for j in range(d):
                s = sum(self.matrix[k * d + i].conjugate() * self.matrix[k * d + j]
                        for k in range(d))
                expected = 1.0 if i == j else 0.0
                if abs(s - expected) > eps:
                    return False
        return True

    def dagger(self) -> "Gate":
        """Return the conjugate transpose (adjoint) gate."""
        d = self.dim
        mat = [self.matrix[j * d + i].conjugate() for i in range(d) for j in range(d)]
        return Gate(self.name + "†", mat, self.n_qubits)

    def __repr__(self) -> str:
        return f"Gate({self.name})"


# ------------------------------------------------------------------
# Gate definitions (2×2 single-qubit)
# ------------------------------------------------------------------

def _g1(name, a, b, c, d) -> Gate:
    return Gate(name, [complex(a), complex(b), complex(c), complex(d)], 1)

def _phase(theta: float) -> complex:
    return cmath.exp(1j * theta)


# Standard single-qubit gates
GATES = {
    "I":   _g1("I",   1, 0, 0, 1),
    "X":   _g1("X",   0, 1, 1, 0),
    "Y":   _g1("Y",   0, -1j, 1j, 0),
    "Z":   _g1("Z",   1, 0, 0, -1),
    "H":   Gate("H",  [_SQRT2_INV, _SQRT2_INV, _SQRT2_INV, -_SQRT2_INV], 1),
    "S":   _g1("S",   1, 0, 0, 1j),
    "Sdg": _g1("Sdg", 1, 0, 0, -1j),
    "T":   Gate("T",  [1, 0, 0, _phase(math.pi/4)], 1),
    "Tdg": Gate("Tdg",[1, 0, 0, _phase(-math.pi/4)], 1),
    "CNOT": Gate("CNOT", [1,0,0,0, 0,1,0,0, 0,0,0,1, 0,0,1,0], 2),
    "CX":   Gate("CX",   [1,0,0,0, 0,1,0,0, 0,0,0,1, 0,0,1,0], 2),
    "CZ":   Gate("CZ",   [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,-1], 2),
    "SWAP": Gate("SWAP", [1,0,0,0, 0,0,1,0, 0,1,0,0, 0,0,0,1], 2),
    "iSWAP": Gate("iSWAP",[1,0,0,0, 0,0,1j,0, 0,1j,0,0, 0,0,0,1], 2),
    "Toffoli": Gate("Toffoli", [
        1,0,0,0,0,0,0,0,
        0,1,0,0,0,0,0,0,
        0,0,1,0,0,0,0,0,
        0,0,0,1,0,0,0,0,
        0,0,0,0,1,0,0,0,
        0,0,0,0,0,1,0,0,
        0,0,0,0,0,0,0,1,
        0,0,0,0,0,0,1,0,
    ], 3),
    "Fredkin": Gate("Fredkin", [
        1,0,0,0,0,0,0,0,
        0,1,0,0,0,0,0,0,
        0,0,1,0,0,0,0,0,
        0,0,0,1,0,0,0,0,
        0,0,0,0,1,0,0,0,
        0,0,0,0,0,0,1,0,
        0,0,0,0,0,1,0,0,
        0,0,0,0,0,0,0,1,
    ], 3),
}


def Rx(theta: float) -> Gate:
    """Rotation around X axis: Rx(θ) = exp(-iθX/2)."""
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return Gate(f"Rx({theta:.4g})", [c, -1j*s, -1j*s, c], 1)

def Ry(theta: float) -> Gate:
    """Rotation around Y axis: Ry(θ) = exp(-iθY/2)."""
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return Gate(f"Ry({theta:.4g})", [c, -s, s, c], 1)

def Rz(theta: float) -> Gate:
    """Rotation around Z axis: Rz(θ) = exp(-iθZ/2)."""
    e_neg = cmath.exp(-1j * theta / 2)
    e_pos = cmath.exp(1j * theta / 2)
    return Gate(f"Rz({theta:.4g})", [e_neg, 0, 0, e_pos], 1)

def Phase(theta: float) -> Gate:
    """Phase gate: P(θ) = diag(1, e^{iθ})."""
    return Gate(f"P({theta:.4g})", [1, 0, 0, cmath.exp(1j * theta)], 1)

def U(theta: float, phi: float, lam: float) -> Gate:
    """General single-qubit gate (IBM convention):
    U(θ,φ,λ) = [[cos(θ/2), -e^{iλ}sin(θ/2)],
                 [e^{iφ}sin(θ/2), e^{i(φ+λ)}cos(θ/2)]]
    """
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return Gate(
        f"U({theta:.4g},{phi:.4g},{lam:.4g})",
        [
            c, -cmath.exp(1j * lam) * s,
            cmath.exp(1j * phi) * s, cmath.exp(1j * (phi + lam)) * c,
        ],
        1,
    )

def controlled(gate: Gate, n_ctrl: int = 1) -> Gate:
    """
    Create an n_ctrl-controlled version of a k-qubit gate.
    Resulting gate: (n_ctrl + k) qubits.
    Acts as identity unless all control qubits are |1⟩.
    """
    k = gate.n_qubits
    total_n = n_ctrl + k
    total_dim = 1 << total_n
    identity_part = 1 << (total_dim - (1 << k))  # index threshold
    mat = []
    for row in range(total_dim):
        for col in range(total_dim):
            ctrl_mask = ((1 << n_ctrl) - 1) << k
            ctrl_bits_row = (row >> k) & ((1 << n_ctrl) - 1)
            ctrl_bits_col = (col >> k) & ((1 << n_ctrl) - 1)
            tgt_row = row & ((1 << k) - 1)
            tgt_col = col & ((1 << k) - 1)
            all_ctrl = (1 << n_ctrl) - 1
            if ctrl_bits_row == all_ctrl and ctrl_bits_col == all_ctrl:
                # In the all-1 control subspace: apply gate
                mat.append(gate.matrix[tgt_row * (1 << k) + tgt_col])
            else:
                # Identity on all other subspaces
                mat.append(1.0 + 0.0j if row == col else 0.0 + 0.0j)
    return Gate(f"C{n_ctrl}-{gate.name}", mat, total_n)

def custom(name: str, matrix: list, n_qubits: int = 1) -> Gate:
    """Create a gate from a user-supplied matrix (flat, row-major, complex)."""
    return Gate(name, [complex(x) for x in matrix], n_qubits)


# ------------------------------------------------------------------
# Efficient O(2^n) gate application
# ------------------------------------------------------------------

def apply_1q(state: QuantumState, gate: Gate, qubit: int) -> QuantumState:
    """
    Apply a single-qubit gate to `qubit`.

    For each pair of amplitudes that differ only in bit `qubit`:
        new[...0...] = a·old[...0...] + b·old[...1...]
        new[...1...] = c·old[...0...] + d·old[...1...]

    O(2^n) time, O(2^n) space.
    """
    if qubit < 0 or qubit >= state.n:
        raise ValueError(f"Qubit {qubit} out of range [0, {state.n})")
    a, b, c, d = gate.matrix
    n = state.n
    amp = list(state._amp)
    # bit position in the index corresponding to this qubit
    # qubit 0 = MSB = bit (n-1) in the integer index
    bit = n - 1 - qubit
    mask = 1 << bit
    half = state.dim >> 1

    for i in range(state.dim):
        if i & mask:
            continue  # only visit the '0' member of each pair
        j = i | mask   # partner with bit set
        a0, a1 = amp[i], amp[j]
        amp[i] = a * a0 + b * a1
        amp[j] = c * a0 + d * a1

    new_state = QuantumState(n)
    new_state._amp = amp
    return new_state


def apply_2q(state: QuantumState, gate: Gate, qubit0: int, qubit1: int) -> QuantumState:
    """
    Apply a two-qubit gate to (qubit0, qubit1).

    Gate matrix rows/cols are indexed: 00, 01, 10, 11
    where '0' = qubit0 state, '1' = qubit1 state.
    """
    if gate.n_qubits != 2:
        raise ValueError("Expected a 2-qubit gate")
    n = state.n
    if not (0 <= qubit0 < n and 0 <= qubit1 < n and qubit0 != qubit1):
        raise ValueError(f"Invalid qubit indices ({qubit0}, {qubit1}) for n={n}")

    m = gate.matrix  # 4×4 flat
    amp = list(state._amp)

    bit0 = n - 1 - qubit0  # MSB position for qubit0
    bit1 = n - 1 - qubit1
    mask0 = 1 << bit0
    mask1 = 1 << bit1

    for i in range(state.dim):
        if (i & mask0) or (i & mask1):
            continue  # only visit the '00' representative
        i00 = i
        i01 = i | mask1
        i10 = i | mask0
        i11 = i | mask0 | mask1
        v00, v01, v10, v11 = amp[i00], amp[i01], amp[i10], amp[i11]
        amp[i00] = m[0]*v00 + m[1]*v01 + m[2]*v10 + m[3]*v11
        amp[i01] = m[4]*v00 + m[5]*v01 + m[6]*v10 + m[7]*v11
        amp[i10] = m[8]*v00 + m[9]*v01 + m[10]*v10 + m[11]*v11
        amp[i11] = m[12]*v00 + m[13]*v01 + m[14]*v10 + m[15]*v11

    new_state = QuantumState(n)
    new_state._amp = amp
    return new_state


def apply_3q(state: QuantumState, gate: Gate,
             qubit0: int, qubit1: int, qubit2: int) -> QuantumState:
    """
    Apply a three-qubit gate to (qubit0, qubit1, qubit2).
    Gate indices: 000, 001, 010, 011, 100, 101, 110, 111
    """
    if gate.n_qubits != 3:
        raise ValueError("Expected a 3-qubit gate")
    n = state.n
    qubits = [qubit0, qubit1, qubit2]
    if len(set(qubits)) != 3 or any(q < 0 or q >= n for q in qubits):
        raise ValueError(f"Invalid qubits {qubits} for n={n}")

    m = gate.matrix  # 8×8 flat
    amp = list(state._amp)

    bits = [n - 1 - q for q in qubits]
    masks = [1 << b for b in bits]

    for i in range(state.dim):
        if any(i & mk for mk in masks):
            continue
        # The 8 indices: (0|1 for each qubit)
        idxs = [0] * 8
        for combo in range(8):
            idx = i
            for bit_pos in range(3):
                if (combo >> (2 - bit_pos)) & 1:
                    idx |= masks[bit_pos]
            idxs[combo] = idx
        vals = [amp[idx] for idx in idxs]
        for row in range(8):
            amp[idxs[row]] = sum(m[row * 8 + col] * vals[col] for col in range(8))

    new_state = QuantumState(n)
    new_state._amp = amp
    return new_state


def apply_gate(state: QuantumState, gate: Gate, qubits: list) -> QuantumState:
    """
    Universal gate applicator: dispatches to the appropriate 1/2/3-qubit
    function, or falls back to the general tensor-product method.
    """
    k = gate.n_qubits
    if len(qubits) != k:
        raise ValueError(f"{gate.name} needs {k} qubits, got {len(qubits)}")
    if k == 1:
        return apply_1q(state, gate, qubits[0])
    if k == 2:
        return apply_2q(state, gate, qubits[0], qubits[1])
    if k == 3:
        return apply_3q(state, gate, qubits[0], qubits[1], qubits[2])
    # General: build the full 2^n × 2^n matrix and multiply (slow for large n)
    return _apply_general(state, gate, qubits)


def _apply_general(state: QuantumState, gate: Gate, qubits: list) -> QuantumState:
    """Fallback: general k-qubit gate via full state-vector contraction."""
    n = state.n
    k = gate.n_qubits
    dim = state.dim
    amp = list(state._amp)
    new_amp = [0.0 + 0.0j] * dim
    bits = [n - 1 - q for q in qubits]

    for i in range(dim):
        if any((i >> b) & 1 for b in bits):
            continue  # only visit 'all-zero' representatives
        # collect 2^k indices
        idxs = []
        for combo in range(1 << k):
            idx = i
            for bit_pos in range(k):
                if (combo >> (k - 1 - bit_pos)) & 1:
                    idx |= 1 << bits[bit_pos]
            idxs.append(idx)
        vals = [amp[idx] for idx in idxs]
        for row in range(1 << k):
            s = sum(gate.matrix[row * (1 << k) + col] * vals[col]
                    for col in range(1 << k))
            new_amp[idxs[row]] = s

    new_state = QuantumState(n)
    new_state._amp = new_amp
    return new_state
