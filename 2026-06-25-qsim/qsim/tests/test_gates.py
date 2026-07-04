"""Tests for gate library: unitarity, truth tables, compositions."""

import math
import cmath
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qsim.gates import (
    GATES, Gate, Rx, Ry, Rz, Phase, U,
    controlled, apply_1q, apply_2q, apply_3q, apply_gate,
)
from qsim.state import QuantumState


def _mat_mul(A, B, n):
    """n×n matrix multiply (flat lists, row-major)."""
    C = [0j] * (n * n)
    for i in range(n):
        for j in range(n):
            for k in range(n):
                C[i * n + j] += A[i * n + k] * B[k * n + j]
    return C


def _mat_dag(M, n):
    """Conjugate transpose of n×n matrix."""
    D = [0j] * (n * n)
    for i in range(n):
        for j in range(n):
            D[j * n + i] = M[i * n + j].conjugate()
    return D


def _is_identity(M, n, tol=1e-10):
    """Check M ≈ I."""
    for i in range(n):
        for j in range(n):
            expected = 1.0 if i == j else 0.0
            if abs(M[i * n + j] - expected) > tol:
                return False
    return True


def test_all_standard_gates_unitary():
    """Every gate in GATES must be unitary: U†U = I."""
    for name, g in GATES.items():
        n = 1 << g.n_qubits
        dag = _mat_dag(g.matrix, n)
        prod = _mat_mul(dag, g.matrix, n)
        assert _is_identity(prod, n, tol=1e-10), \
            f"Gate {name} is not unitary: U†U ≠ I"


def test_parameterized_gates_unitary():
    """Rx, Ry, Rz, Phase, U must all be unitary."""
    angles = [0.0, math.pi / 6, math.pi / 4, math.pi / 2, math.pi, 2 * math.pi]
    for theta in angles:
        for g in [Rx(theta), Ry(theta), Rz(theta), Phase(theta)]:
            n = 1 << g.n_qubits
            dag = _mat_dag(g.matrix, n)
            prod = _mat_mul(dag, g.matrix, n)
            assert _is_identity(prod, n, tol=1e-10), \
                f"{g.name}({theta:.3f}) is not unitary"
    g = U(math.pi / 2, math.pi / 4, math.pi / 8)
    n = 2
    dag = _mat_dag(g.matrix, n)
    prod = _mat_mul(dag, g.matrix, n)
    assert _is_identity(prod, n, tol=1e-10), "U gate is not unitary"


def test_hadamard_self_inverse():
    """HH = I."""
    H = GATES["H"]
    state = QuantumState.zero(1)
    state = apply_1q(state, H, 0)
    state = apply_1q(state, H, 0)
    assert abs(state._amp[0] - 1.0) < 1e-14, "HH|0⟩ ≠ |0⟩"
    assert abs(state._amp[1] - 0.0) < 1e-14, "HH|0⟩ ≠ |0⟩"


def test_hadamard_plus_state():
    """H|0⟩ = |+⟩ = (|0⟩+|1⟩)/√2."""
    H = GATES["H"]
    s = math.sqrt(0.5)
    state = apply_1q(QuantumState.zero(1), H, 0)
    assert abs(state._amp[0] - s) < 1e-14
    assert abs(state._amp[1] - s) < 1e-14


def test_x_gate():
    """X|0⟩ = |1⟩, X|1⟩ = |0⟩."""
    X = GATES["X"]
    s0 = QuantumState.zero(1)
    s1 = apply_1q(s0, X, 0)
    assert abs(s1._amp[0]) < 1e-14 and abs(s1._amp[1] - 1.0) < 1e-14
    s2 = apply_1q(s1, X, 0)
    assert abs(s2._amp[0] - 1.0) < 1e-14 and abs(s2._amp[1]) < 1e-14


def test_z_gate():
    """Z|0⟩ = |0⟩, Z|1⟩ = -|1⟩."""
    X, Z = GATES["X"], GATES["Z"]
    s = apply_1q(apply_1q(QuantumState.zero(1), X, 0), Z, 0)
    assert abs(s._amp[0]) < 1e-14
    assert abs(s._amp[1] - (-1.0)) < 1e-14


def test_rx_pi_on_zero():
    """Rx(π)|0⟩ = -i|1⟩."""
    state = apply_1q(QuantumState.zero(1), Rx(math.pi), 0)
    assert abs(state._amp[0]) < 1e-14, "Rx(π)|0⟩ should have zero |0⟩ amplitude"
    assert abs(state._amp[1] - (-1j)) < 1e-14, f"Rx(π)|0⟩ should be -i|1⟩, got {state._amp[1]}"


def test_rx_2pi_minus_identity():
    """Rx(2π) = -I (global phase)."""
    Rx2pi = Rx(2 * math.pi)
    state = apply_1q(QuantumState.zero(1), Rx2pi, 0)
    assert abs(state._amp[0] - (-1.0)) < 1e-14, f"Rx(2π)|0⟩ should be -|0⟩, got {state._amp[0]}"


def test_cnot_truth_table():
    """CNOT truth table: |00⟩→|00⟩, |01⟩→|01⟩, |10⟩→|11⟩, |11⟩→|10⟩."""
    CNOT = GATES["CNOT"]
    expected = {0: 0, 1: 1, 2: 3, 3: 2}  # index → output index
    for idx, out_idx in expected.items():
        s = QuantumState.from_basis(2, idx)
        s2 = apply_2q(s, CNOT, 0, 1)
        for k in range(4):
            exp = 1.0 if k == out_idx else 0.0
            assert abs(abs(s2._amp[k]) - exp) < 1e-14, \
                f"CNOT|{idx:02b}⟩: amp[{k}]={s2._amp[k]:.4f}, expected {exp}"


def test_cnot_reversed():
    """CNOT with control=1, target=0: |01⟩ (q1=1 control fires) → |11⟩."""
    CNOT = GATES["CNOT"]
    # Big-endian: |01⟩ = q0=0, q1=1 → index 1. ctrl=qubit1=1 fires, flips qubit0: → |11⟩ (idx 3)
    s = QuantumState.from_basis(2, 1)  # |01⟩: q0=0, q1=1
    s2 = apply_2q(s, CNOT, 1, 0)      # control=qubit1(=1), target=qubit0
    assert abs(s2._amp[3] - 1.0) < 1e-14, \
        f"CNOT(ctrl=1,tgt=0)|01⟩ should give |11⟩, got amps={s2._amp}"
    # Also verify: |10⟩ (q1=0 → ctrl not active) → |10⟩ unchanged
    s3 = QuantumState.from_basis(2, 2)  # |10⟩: q0=1, q1=0
    s4 = apply_2q(s3, CNOT, 1, 0)
    assert abs(s4._amp[2] - 1.0) < 1e-14, \
        f"CNOT(ctrl=1,tgt=0)|10⟩ with inactive ctrl should stay |10⟩"


def test_toffoli_truth_table():
    """Toffoli (CCX) truth table: only |110⟩→|111⟩ and |111⟩→|110⟩ differ."""
    CCX = GATES["Toffoli"]
    flipped = {6: 7, 7: 6}
    for idx in range(8):
        s = QuantumState.from_basis(3, idx)
        s2 = apply_3q(s, CCX, 0, 1, 2)
        out_idx = flipped.get(idx, idx)
        assert abs(s2._amp[out_idx] - 1.0) < 1e-14, \
            f"Toffoli|{idx:03b}⟩ expected |{out_idx:03b}⟩"


def test_fredkin_truth_table():
    """Fredkin (CSWAP): ctrl=0 → identity; ctrl=1 → swaps qubits 1,2."""
    Fredkin = GATES["Fredkin"]
    for idx in range(8):
        s = QuantumState.from_basis(3, idx)
        s2 = apply_3q(s, Fredkin, 0, 1, 2)
        ctrl = (idx >> 2) & 1
        q1 = (idx >> 1) & 1
        q2 = idx & 1
        if ctrl == 0:
            out_idx = idx  # identity
        else:
            out_idx = (ctrl << 2) | (q2 << 1) | q1  # swap q1, q2
        assert abs(s2._amp[out_idx] - 1.0) < 1e-14, \
            f"Fredkin|{idx:03b}⟩ expected |{out_idx:03b}⟩"


def test_cz_symmetry():
    """CZ is symmetric under qubit-order swap."""
    CZ = GATES["CZ"]
    for idx in range(4):
        s = QuantumState.from_basis(2, idx)
        s_01 = apply_2q(s, CZ, 0, 1)
        s_10 = apply_2q(s, CZ, 1, 0)
        for k in range(4):
            assert abs(s_01._amp[k] - s_10._amp[k]) < 1e-14, \
                f"CZ not symmetric for |{idx:02b}⟩"


def test_swap_symmetry():
    """SWAP is symmetric under qubit-order swap."""
    SWAP = GATES["SWAP"]
    for idx in range(4):
        s = QuantumState.from_basis(2, idx)
        s_01 = apply_2q(s, SWAP, 0, 1)
        s_10 = apply_2q(s, SWAP, 1, 0)
        for k in range(4):
            assert abs(s_01._amp[k] - s_10._amp[k]) < 1e-14, \
                f"SWAP not symmetric for |{idx:02b}⟩"


def test_iswap():
    """iSWAP: |01⟩ → i|10⟩."""
    iSWAP = GATES["iSWAP"]
    s = QuantumState.from_basis(2, 1)  # |01⟩
    s2 = apply_2q(s, iSWAP, 0, 1)
    assert abs(s2._amp[2] - 1j) < 1e-14, f"iSWAP|01⟩ should give i|10⟩, got {s2._amp[2]}"
    assert abs(s2._amp[1]) < 1e-14


def test_controlled_x_equals_cnot():
    """controlled(X) should behave identically to CNOT."""
    from qsim.gates import controlled
    ctrl_x = controlled(GATES["X"])
    CNOT = GATES["CNOT"]
    for idx in range(4):
        s = QuantumState.from_basis(2, idx)
        s1 = apply_2q(s, ctrl_x, 0, 1)
        s2 = apply_2q(s, CNOT, 0, 1)
        for k in range(4):
            assert abs(s1._amp[k] - s2._amp[k]) < 1e-12, \
                f"controlled(X)|{idx:02b}⟩ differs from CNOT"


def test_controlled_controlled_x_equals_toffoli():
    """controlled(controlled(X)) should equal Toffoli."""
    from qsim.gates import controlled
    ccx = controlled(controlled(GATES["X"]))
    Toffoli = GATES["Toffoli"]
    for idx in range(8):
        s = QuantumState.from_basis(3, idx)
        s1 = apply_3q(s, ccx, 0, 1, 2)
        s2 = apply_3q(s, Toffoli, 0, 1, 2)
        for k in range(8):
            assert abs(s1._amp[k] - s2._amp[k]) < 1e-12, \
                f"controlled²(X)|{idx:03b}⟩ differs from Toffoli"


def test_norm_conservation():
    """Random gate sequences must preserve state norm."""
    import random
    rng = random.Random(1234)
    gate_names = ["H", "X", "Y", "Z", "S", "T", "Sdg", "Tdg"]
    for _ in range(50):
        state = QuantumState.zero(3)
        for __ in range(20):
            g = GATES[rng.choice(gate_names)]
            q = rng.randint(0, 2)
            state = apply_1q(state, g, q)
        norm_sq = sum(abs(a) ** 2 for a in state._amp)
        assert abs(norm_sq - 1.0) < 1e-10, f"Norm not preserved: {norm_sq}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
