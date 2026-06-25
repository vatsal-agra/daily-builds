"""Tests for noise channels: Kraus completeness, statistical correctness, no-noise baseline."""

import math
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qsim.state import QuantumState
from qsim.gates import GATES, apply_1q
from qsim.noise import (
    NoiseChannel, NoiseModel,
    bit_flip_channel, phase_flip_channel, depolarizing_channel,
    amplitude_damping_channel, phase_damping_channel,
)
from qsim.measure import sample


def _kraus_completeness(channel: NoiseChannel, tol=1e-12) -> bool:
    """Check that sum of K†K = I for all Kraus operators."""
    n = channel.dim
    I = [0j] * (n * n)
    for i in range(n):
        I[i * n + i] = 1.0 + 0j

    total = [0j] * (n * n)
    for K in channel.kraus_ops:
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    total[j * n + i] += K[k * n + j].conjugate() * K[k * n + i]

    for i in range(n * n):
        if abs(total[i] - I[i]) > tol:
            return False
    return True


def test_bit_flip_kraus_completeness():
    for p in [0.0, 0.1, 0.5, 0.9, 1.0]:
        ch = bit_flip_channel(p)
        assert _kraus_completeness(ch), f"bit_flip({p}) Kraus not complete"


def test_phase_flip_kraus_completeness():
    for p in [0.0, 0.1, 0.5, 1.0]:
        ch = phase_flip_channel(p)
        assert _kraus_completeness(ch), f"phase_flip({p}) Kraus not complete"


def test_depolarizing_kraus_completeness():
    for p in [0.0, 0.05, 0.1, 0.3]:
        ch = depolarizing_channel(p)
        assert _kraus_completeness(ch), f"depolarizing({p}) Kraus not complete"


def test_amplitude_damping_kraus_completeness():
    for gamma in [0.0, 0.1, 0.5, 1.0]:
        ch = amplitude_damping_channel(gamma)
        assert _kraus_completeness(ch), f"amplitude_damping({gamma}) Kraus not complete"


def test_phase_damping_kraus_completeness():
    for lam in [0.0, 0.1, 0.5, 1.0]:
        ch = phase_damping_channel(lam)
        assert _kraus_completeness(ch), f"phase_damping({lam}) Kraus not complete"


def test_bit_flip_zero_p_identity():
    """bit_flip(0): no error channel, state unchanged."""
    rng = random.Random(0)
    ch = bit_flip_channel(0.0)
    state = QuantumState(1, [1 / math.sqrt(2), 1j / math.sqrt(2)])
    # Apply many times: state should be unchanged
    for _ in range(50):
        new = ch.apply(state, 0, rng)
        for k in range(2):
            assert abs(new._amp[k] - state._amp[k]) < 1e-12


def test_bit_flip_p1_always_flips():
    """bit_flip(1): always applies X."""
    rng = random.Random(1)
    ch = bit_flip_channel(1.0)
    state = QuantumState.zero(1)  # |0⟩
    for _ in range(20):
        new = ch.apply(state, 0, rng)
        # |0⟩ → X|0⟩ = |1⟩ with p=1
        assert abs(new._amp[1] - 1.0) < 1e-12, "bit_flip(1) should always flip |0⟩"


def test_bit_flip_statistics():
    """bit_flip(p=0.1) on |0⟩: P(final |1⟩) ≈ 0.1."""
    rng = random.Random(99)
    ch = bit_flip_channel(0.1)
    N = 5000
    flips = 0
    for _ in range(N):
        state = QuantumState.zero(1)
        new = ch.apply(state, 0, rng)
        # Measure: if |1⟩ amplitude is 1, a flip occurred
        if abs(new._amp[1] - 1.0) < 0.5:
            flips += 1
    p_flip = flips / N
    assert 0.07 < p_flip < 0.13, f"bit_flip(0.1) flip rate={p_flip:.3f}, expected ~0.1"


def test_amplitude_damping_gamma1():
    """amplitude_damping(1): |1⟩ always decays to |0⟩."""
    rng = random.Random(2)
    ch = amplitude_damping_channel(1.0)
    X = GATES["X"]
    state = apply_1q(QuantumState.zero(1), X, 0)  # |1⟩
    for _ in range(20):
        new = ch.apply(state, 0, rng)
        assert abs(new._amp[0] - 1.0) < 1e-12, "amplitude_damping(1) should decay |1⟩→|0⟩"


def test_amplitude_damping_zero_ground():
    """amplitude_damping on |0⟩: ground state is fixed point."""
    rng = random.Random(3)
    ch = amplitude_damping_channel(0.5)
    state = QuantumState.zero(1)
    for _ in range(50):
        new = ch.apply(state, 0, rng)
        assert abs(new._amp[0] - 1.0) < 1e-12, "|0⟩ should be fixed by amplitude damping"


def test_amplitude_damping_excited_decay():
    """amplitude_damping(γ=0.3) on |1⟩: P(staying |1⟩) ≈ 1-γ = 0.7."""
    rng = random.Random(42)
    ch = amplitude_damping_channel(0.3)
    X = GATES["X"]
    state = apply_1q(QuantumState.zero(1), X, 0)  # |1⟩
    N = 5000
    stayed = 0
    for _ in range(N):
        new = ch.apply(state, 0, rng)
        if abs(new._amp[1] - 1.0) < 0.5:
            stayed += 1
    p_stay = stayed / N
    assert 0.65 < p_stay < 0.75, f"amplitude_damping(0.3): P(stay)={p_stay:.3f}, expected ~0.7"


def test_noise_model_depolarizing():
    """NoiseModel.depolarizing(p=0): ideal Bell pair statistics preserved."""
    from qsim.circuit import Circuit
    rng = random.Random(0)
    qc = Circuit(2, 2, name="bell")
    qc.h(0)
    qc.cnot(0, 1)
    qc.measure(0, 0)
    qc.measure(1, 1)

    ideal = qc.run(shots=2000, rng=rng)
    counts = ideal.counts
    # Bell pair should only give 00 or 11
    assert counts.get("01", 0) == 0 and counts.get("10", 0) == 0, \
        f"Ideal Bell pair gave unexpected outcomes: {counts}"


def test_noise_model_depolarizing_nonzero():
    """NoiseModel.depolarizing(0.1) on Bell pair introduces errors."""
    from qsim.circuit import Circuit
    rng = random.Random(7)
    qc = Circuit(2, 2, name="bell-noisy")
    qc.h(0)
    qc.cnot(0, 1)
    qc.measure(0, 0)
    qc.measure(1, 1)

    nm = NoiseModel.depolarizing(0.10)
    r = qc.run(shots=2000, rng=rng, noise_model=nm)
    # Should see some '01' and '10' errors
    error_rate = (r.counts.get("01", 0) + r.counts.get("10", 0)) / 2000
    assert error_rate > 0.01, \
        f"Depolarizing noise should introduce errors, got error_rate={error_rate:.3f}"


def test_no_noise_single_shot_deterministic():
    """Circuit without noise: multiple shots of a deterministic circuit agree."""
    from qsim.circuit import Circuit
    qc = Circuit(2, 2, name="det")
    qc.x(0)
    qc.x(1)
    qc.measure(0, 0)
    qc.measure(1, 1)
    r = qc.run(shots=100, rng=random.Random(0))
    assert r.counts == {"11": 100}, f"Expected all '11', got {r.counts}"


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
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
