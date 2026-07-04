"""Tests for quantum algorithms: correctness, edge cases, error handling."""

import math
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qsim.algorithms import (
    deutsch_jozsa, bernstein_vazirani, grover, qft_circuit, verify_qft,
    quantum_phase_estimation, teleportation, simon, bb84, superdense_coding,
)
from qsim.state import QuantumState


RNG = random.Random(2025)


def test_deutsch_jozsa_constant_zero():
    """Constant-0 oracle → 'constant'."""
    r = deutsch_jozsa(4, "constant_0", rng=random.Random(1))
    assert r['result'] == 'constant' and r['verified']


def test_deutsch_jozsa_constant_one():
    """Constant-1 oracle → 'constant'."""
    r = deutsch_jozsa(3, "constant_1", rng=random.Random(2))
    assert r['result'] == 'constant' and r['verified']


def test_deutsch_jozsa_balanced():
    """Balanced oracle → 'balanced'."""
    for n in range(1, 6):
        r = deutsch_jozsa(n, "balanced", rng=random.Random(n))
        assert r['result'] == 'balanced' and r['verified'], \
            f"DJ balanced failed for n={n}"


def test_deutsch_jozsa_balanced_parity():
    """Balanced-parity oracle with custom secret bits."""
    r = deutsch_jozsa(4, "balanced_parity", secret_bits="1010", rng=random.Random(3))
    assert r['result'] == 'balanced' and r['verified']


def test_bernstein_vazirani_various_secrets():
    """BV recovers the hidden string for various lengths."""
    secrets = ["0", "1", "10110", "111000", "0101010"]
    for s in secrets:
        r = bernstein_vazirani(s, rng=random.Random(len(s)))
        assert r['result'] == s and r['verified'], \
            f"BV failed for secret='{s}': got '{r['result']}'"


def test_bernstein_vazirani_all_zeros():
    """BV with all-zeros secret."""
    s = "000"
    r = bernstein_vazirani(s, rng=random.Random(0))
    assert r['result'] == s and r['verified']


def test_bernstein_vazirani_bad_input():
    """BV should reject non-binary secrets."""
    try:
        bernstein_vazirani("102")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_grover_n2_all_targets():
    """Grover n=2: all 4 targets should succeed (tests the exact iteration formula)."""
    for t in range(4):
        r = grover(2, [t], rng=random.Random(t))
        assert r['verified'], f"Grover n=2 target={t} failed"
        assert r['success_prob'] > 0.99, \
            f"Grover n=2 target={t}: success_prob={r['success_prob']:.4f}"


def test_grover_n3_all_targets():
    """Grover n=3: all 8 targets."""
    for t in range(8):
        r = grover(3, [t], rng=random.Random(t + 100))
        assert r['verified'], f"Grover n=3 target={t} failed"


def test_grover_n4_single_target():
    """Grover n=4: single target search."""
    r = grover(4, [7], rng=random.Random(42))
    assert r['verified'], f"Grover n=4 target=7 failed"


def test_grover_multiple_targets():
    """Grover with multiple marked items."""
    r = grover(4, [2, 8, 13], rng=random.Random(42))
    assert r['verified'], f"Grover multi-target failed, found {r['result_int']}"


def test_grover_out_of_range():
    """Grover should reject out-of-range targets."""
    try:
        grover(3, [8])  # 8 >= 2^3
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_qft_exact_matrix_n2():
    """QFT on n=2: max error vs DFT matrix < 1e-14."""
    r = verify_qft(2)
    assert r['verified'] and r['max_error'] < 1e-14


def test_qft_exact_matrix_n3():
    r = verify_qft(3)
    assert r['verified']


def test_qft_exact_matrix_n4():
    r = verify_qft(4)
    assert r['verified']


def test_qft_iqft_identity():
    """QFT × IQFT = I for n=2,3,4."""
    from qsim.algorithms import qft_circuit
    for n in [2, 3, 4]:
        N = 1 << n
        qft = qft_circuit(n)
        iqft = qft_circuit(n, inverse=True)
        max_err = 0.0
        for x in range(N):
            init = QuantumState.from_basis(n, x)
            r1 = qft.run(initial_state=init, shots=1)
            r2 = iqft.run(initial_state=r1.final_state, shots=1)
            for k in range(N):
                exp = 1.0 if k == x else 0.0
                err = abs(abs(r2.final_state._amp[k]) - exp)
                if err > max_err:
                    max_err = err
        assert max_err < 1e-12, f"QFT×IQFT n={n}: max_err={max_err:.2e}"


def test_qpe_representable_phases():
    """QPE should exactly estimate phases representable by n_count bits."""
    for n_count in [3, 4, 5]:
        for k in range(1 << n_count):
            phase = k / (1 << n_count)
            r = quantum_phase_estimation(n_count, phase, rng=random.Random(k))
            assert r['verified'], \
                f"QPE n={n_count} phase={phase:.4f}: error={r['error']:.2e}"
            assert r['error'] < 1e-9, \
                f"QPE exact phase error too large: {r['error']:.2e}"


def test_qpe_non_representable_phase():
    """QPE on non-representable phase: error < 1 LSB = 1/2^n."""
    r = quantum_phase_estimation(4, 0.3333, rng=random.Random(0))
    assert r['verified'], f"QPE 1/3: error={r['error']:.4f} > 1/{1<<4}"


def test_qpe_normalizes_input():
    """QPE should reduce phase mod 1 (e.g., 1.375 → 0.375)."""
    r4 = quantum_phase_estimation(4, 1.375, rng=random.Random(0))
    r0 = quantum_phase_estimation(4, 0.375, rng=random.Random(0))
    assert abs(r4['true_phase'] - r0['true_phase']) < 1e-14


def test_teleportation_fidelity():
    """Teleportation: fidelity = 1.0 over 30 random trials."""
    from qsim.state import QuantumState
    psi = QuantumState(1, [1 / math.sqrt(2), 1j / math.sqrt(2)])
    for i in range(30):
        r = teleportation(psi, rng=random.Random(i))
        assert r['fidelity'] > 0.9999, \
            f"Teleportation trial {i}: fidelity={r['fidelity']:.6f}"


def test_teleportation_all_basis_states():
    """Teleportation of |0⟩ and |1⟩ exactly."""
    for amp in ([1.0, 0.0], [0.0, 1.0]):
        psi = QuantumState(1, amp)
        for i in range(5):
            r = teleportation(psi, rng=random.Random(i))
            assert r['fidelity'] > 0.9999


def test_teleportation_bad_input():
    """Teleportation rejects 2-qubit input."""
    try:
        teleportation(QuantumState.zero(2))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_simon_various_periods():
    """Simon's algorithm recovers the correct period."""
    cases = [(2, "01", 10), (2, "11", 20), (3, "101", 30), (3, "110", 40), (4, "1010", 50)]
    for n, period, seed in cases:
        r = simon(n, period, rng=random.Random(seed))
        assert r['verified'], f"Simon n={n} period='{period}': found '{r['period']}'"


def test_simon_validation():
    """Simon should reject invalid period strings."""
    try:
        simon(3, "1001")  # 4-bit period for n=3
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    try:
        simon(3, "102")  # non-binary
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    try:
        simon(3, "000")  # all-zeros period
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_bb84_no_eavesdrop():
    """BB84 without Eve: QBER=0, keys match, no eavesdrop detected."""
    r = bb84(200, eavesdrop=False, rng=random.Random(42))
    assert r['qber'] == 0.0, f"No-Eve BB84 QBER={r['qber']}, expected 0"
    assert r['key_match'], "Keys should match without Eve"
    assert not r['eavesdrop_detected'], "Should not detect Eve when there is none"
    assert r['secure_key_length'] > 50, "Should produce some key bits"


def test_bb84_with_eavesdrop():
    """BB84 with Eve: QBER ~25%, Eve detected."""
    r = bb84(500, eavesdrop=True, rng=random.Random(0))
    assert r['eavesdrop_detected'], \
        f"Eve not detected: QBER={r['qber']:.3f} (expected >0.11)"
    assert r['qber'] > 0.15, f"QBER={r['qber']:.3f} too low (Eve should cause ~25%)"
    assert r['qber'] < 0.40, f"QBER={r['qber']:.3f} unrealistically high"


def test_bb84_sifted_fraction():
    """BB84 sifted key should be ~50% of raw bits."""
    r = bb84(1000, rng=random.Random(1))
    frac = r['sifted_length'] / r['n_bits']
    assert 0.40 < frac < 0.60, f"Sifted fraction = {frac:.3f}, expected ~0.5"


def test_superdense_coding_all_messages():
    """Superdense coding: all 4 messages decoded correctly."""
    for msg in ["00", "01", "10", "11"]:
        r = superdense_coding(msg, rng=random.Random(0))
        assert r['verified'], f"Superdense '{msg}' decoded as '{r['decoded']}'"


def test_superdense_coding_bad_input():
    """Superdense coding rejects invalid messages."""
    for bad in ["", "0", "100", "2a"]:
        try:
            superdense_coding(bad)
            assert False, f"Should have raised ValueError for '{bad}'"
        except ValueError:
            pass


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
