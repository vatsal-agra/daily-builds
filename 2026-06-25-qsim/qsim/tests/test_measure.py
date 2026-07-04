"""Tests for measurement: Born rule, partial collapse, expectation values, sampling."""

import math
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qsim.state import QuantumState
from qsim.gates import GATES, apply_1q, apply_2q
from qsim.measure import (
    measure, measure_qubit, measure_qubits, sample, expectation_value,
    marginal_probabilities,
)


def test_measure_zero_state():
    """Measuring |0⟩ always gives '0'."""
    rng = random.Random(42)
    state = QuantumState.zero(1)
    for _ in range(20):
        outcome, post = measure(state, rng)
        assert outcome == "0", f"Measuring |0⟩ gave {outcome}"
        assert abs(post._amp[0] - 1.0) < 1e-14


def test_measure_one_state():
    """Measuring |1⟩ always gives '1'."""
    rng = random.Random(42)
    X = GATES["X"]
    state = apply_1q(QuantumState.zero(1), X, 0)
    for _ in range(20):
        outcome, post = measure(state, rng)
        assert outcome == "1", f"Measuring |1⟩ gave {outcome}"


def test_measure_plus_state_statistics():
    """Measuring |+⟩ gives 0 and 1 each ~50% (over many shots)."""
    rng = random.Random(99)
    H = GATES["H"]
    state = apply_1q(QuantumState.zero(1), H, 0)
    counts = {"0": 0, "1": 0}
    N = 1000
    for _ in range(N):
        outcome, _ = measure(state, rng)
        counts[outcome] += 1
    p0 = counts["0"] / N
    assert 0.45 < p0 < 0.55, f"|+⟩ measurement gave P(0)={p0:.3f}, expected ~0.5"


def test_measure_collapses_state():
    """After measuring |+⟩ and getting 0, the post-state is |0⟩."""
    rng = random.Random(42)
    H = GATES["H"]
    state = apply_1q(QuantumState.zero(1), H, 0)
    # Find a run that gives outcome '0'
    for _ in range(100):
        outcome, post = measure(state, rng)
        if outcome == "0":
            assert abs(post._amp[0] - 1.0) < 1e-14, "Post-state after '0' should be |0⟩"
            assert abs(post._amp[1]) < 1e-14
            return
    assert False, "Never got '0' outcome in 100 trials"


def test_sample_correct_distribution():
    """sample() on |+⟩ gives counts consistent with P(0)=P(1)=0.5."""
    rng = random.Random(7)
    H = GATES["H"]
    state = apply_1q(QuantumState.zero(1), H, 0)
    counts = sample(state, 2000, rng)
    total = sum(counts.values())
    assert total == 2000
    p0 = counts.get("0", 0) / 2000
    assert 0.47 < p0 < 0.53, f"sample |+⟩: P(0)={p0:.3f}"


def test_sample_deterministic_state():
    """sample() on |00⟩ should give 100% '00'."""
    rng = random.Random(0)
    state = QuantumState.zero(2)
    counts = sample(state, 100, rng)
    assert counts == {"00": 100}, f"Expected all '00', got {counts}"


def test_expectation_value_z_on_zero():
    """⟨Z⟩|0⟩ = +1."""
    state = QuantumState.zero(1)
    ev = expectation_value(state, "Z", 0)
    assert abs(ev - 1.0) < 1e-14, f"⟨Z⟩|0⟩ = {ev}, expected 1"


def test_expectation_value_z_on_one():
    """⟨Z⟩|1⟩ = -1."""
    X = GATES["X"]
    state = apply_1q(QuantumState.zero(1), X, 0)
    ev = expectation_value(state, "Z", 0)
    assert abs(ev - (-1.0)) < 1e-14, f"⟨Z⟩|1⟩ = {ev}, expected -1"


def test_expectation_value_x_on_plus():
    """⟨X⟩|+⟩ = +1."""
    H = GATES["H"]
    state = apply_1q(QuantumState.zero(1), H, 0)
    ev = expectation_value(state, "X", 0)
    assert abs(ev - 1.0) < 1e-14, f"⟨X⟩|+⟩ = {ev}, expected 1"


def test_expectation_value_y_on_y_plus():
    """⟨Y⟩|i+⟩ = +1, where |i+⟩ = (|0⟩+i|1⟩)/√2."""
    s = 1 / math.sqrt(2)
    state = QuantumState(1, [s, 1j * s])
    ev = expectation_value(state, "Y", 0)
    assert abs(ev - 1.0) < 1e-14, f"⟨Y⟩ = {ev}, expected 1"


def test_partial_measure_bell():
    """Measuring qubit 0 of a Bell pair always gives a correlated post-state."""
    rng = random.Random(55)
    H, CNOT = GATES["H"], GATES["CNOT"]
    # Make 200 Bell pairs and measure qubit 0; qubit 1 must match
    for _ in range(200):
        state = apply_2q(apply_1q(QuantumState.zero(2), H, 0), CNOT, 0, 1)
        b, post = measure_qubit(state, 0, rng)
        # Post-state should have qubit 1 = b (collapsed to |bb⟩)
        if b == 0:
            assert abs(post._amp[0] - 1.0) < 1e-12, "Bell: after q0=0, should be |00⟩"
        else:
            assert abs(post._amp[3] - 1.0) < 1e-12, "Bell: after q0=1, should be |11⟩"


def test_measure_qubits_subset():
    """measure_qubits on qubit 0 of Bell state collapses consistently."""
    rng = random.Random(1)
    H, CNOT = GATES["H"], GATES["CNOT"]
    for _ in range(50):
        state = apply_2q(apply_1q(QuantumState.zero(2), H, 0), CNOT, 0, 1)
        result, post = measure_qubits(state, [0], rng)
        b0 = int(result)
        # Check that qubit 1 in post state is definite and matches b0
        p0 = sum(abs(post._amp[i])**2 for i in range(4) if (i >> 1) & 1 == 0)  # q0=0
        p1 = sum(abs(post._amp[i])**2 for i in range(4) if (i >> 1) & 1 == 1)  # q0=1
        # One of p0, p1 should be 1 and match b0
        if b0 == 0:
            assert abs(p0 - 1.0) < 1e-12
        else:
            assert abs(p1 - 1.0) < 1e-12


def test_marginal_probabilities():
    """Marginal probabilities of Bell pair: each qubit 50/50."""
    H, CNOT = GATES["H"], GATES["CNOT"]
    state = apply_2q(apply_1q(QuantumState.zero(2), H, 0), CNOT, 0, 1)
    m = marginal_probabilities(state, [0])
    assert abs(m.get("0", 0) - 0.5) < 1e-14
    assert abs(m.get("1", 0) - 0.5) < 1e-14


def test_bloch_vector_zero_state():
    """|0⟩ should be at north pole: Bloch vector (0, 0, 1)."""
    state = QuantumState.zero(1)
    x, y, z = state.bloch_vector(0)
    assert abs(x) < 1e-14 and abs(y) < 1e-14 and abs(z - 1.0) < 1e-14


def test_bloch_vector_plus_state():
    """|+⟩ should be at (1, 0, 0)."""
    H = GATES["H"]
    state = apply_1q(QuantumState.zero(1), H, 0)
    x, y, z = state.bloch_vector(0)
    assert abs(x - 1.0) < 1e-14 and abs(y) < 1e-14 and abs(z) < 1e-14


def test_entanglement_entropy_bell():
    """Bell pair has entanglement entropy = log(2)."""
    H, CNOT = GATES["H"], GATES["CNOT"]
    state = apply_2q(apply_1q(QuantumState.zero(2), H, 0), CNOT, 0, 1)
    ent = state.entanglement_entropy([0])
    assert abs(ent - math.log(2)) < 1e-10, f"Bell entropy = {ent}, expected {math.log(2)}"


def test_entanglement_entropy_product():
    """Product state |00⟩ has zero entanglement entropy."""
    state = QuantumState.zero(2)
    ent = state.entanglement_entropy([0])
    assert abs(ent) < 1e-14, f"Product state entropy = {ent}, expected 0"


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
