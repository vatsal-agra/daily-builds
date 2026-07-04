"""
Measurement module: Born-rule measurement, partial measurement, expectation values.

Born rule: P(outcome x) = |⟨x|ψ⟩|²
After measuring qubit k and getting outcome b, the post-measurement state is:
  the sub-normalized projection collapsed and renormalized.
"""

import math
import random
from .state import QuantumState


def measure(state: QuantumState, rng: random.Random = None) -> tuple:
    """
    Measure all qubits in the computational basis (single shot).

    Returns (outcome_str, post_state) where:
      - outcome_str: e.g. '101' (bitstring for qubits 0,1,2)
      - post_state:  collapsed QuantumState (one of the basis states)
    """
    if rng is None:
        rng = random.Random()
    probs = state.probabilities()
    r = rng.random()
    cumulative = 0.0
    outcome = len(probs) - 1
    for i, p in enumerate(probs):
        cumulative += p
        if r <= cumulative:
            outcome = i
            break
    outcome_str = format(outcome, f"0{state.n}b")
    post = QuantumState.from_basis(state.n, outcome)
    return outcome_str, post


def measure_qubit(state: QuantumState, qubit: int,
                  rng: random.Random = None) -> tuple:
    """
    Partial measurement: measure a single qubit.

    Returns (outcome_bit, post_state) where:
      - outcome_bit: 0 or 1
      - post_state:  n-qubit state after collapse, renormalized
    """
    if rng is None:
        rng = random.Random()
    n = state.n
    bit = n - 1 - qubit
    mask = 1 << bit

    # Compute P(outcome = 1)
    p1 = sum(abs(state._amp[i]) ** 2 for i in range(state.dim) if i & mask)
    p0 = 1.0 - p1

    outcome = 1 if rng.random() < p1 else 0
    p_outcome = p1 if outcome else p0

    if p_outcome < 1e-15:
        raise ValueError(f"Outcome {outcome} has probability ~0; state inconsistency")

    # Collapse: zero out all amplitudes inconsistent with outcome
    new_amp = []
    inv_sqrt_p = 1.0 / math.sqrt(p_outcome)
    for i, a in enumerate(state._amp):
        bit_val = (i >> bit) & 1
        new_amp.append(a * inv_sqrt_p if bit_val == outcome else 0.0 + 0.0j)

    post = QuantumState(n, new_amp)
    return outcome, post


def measure_qubits(state: QuantumState, qubits: list,
                   rng: random.Random = None) -> tuple:
    """
    Partial measurement of a subset of qubits (in order given).

    Returns (outcome_str, post_state).
    outcome_str is len(qubits) bits corresponding to the measured qubits.
    """
    if rng is None:
        rng = random.Random()
    n = state.n
    k = len(qubits)

    bits = [n - 1 - q for q in qubits]
    num_outcomes = 1 << k
    probs = [0.0] * num_outcomes

    for i, a in enumerate(state._amp):
        # extract the bits for measured qubits
        sub = 0
        for bit_pos, b in enumerate(bits):
            sub |= ((i >> b) & 1) << (k - 1 - bit_pos)
        probs[sub] += abs(a) ** 2

    # Sample outcome
    r = rng.random()
    cumulative = 0.0
    outcome_idx = num_outcomes - 1
    for idx, p in enumerate(probs):
        cumulative += p
        if r <= cumulative:
            outcome_idx = idx
            break

    outcome_str = format(outcome_idx, f"0{k}b")
    p_outcome = probs[outcome_idx]
    if p_outcome < 1e-15:
        raise ValueError("Outcome has near-zero probability")

    inv_sqrt_p = 1.0 / math.sqrt(p_outcome)
    new_amp = []
    for i, a in enumerate(state._amp):
        sub = 0
        for bit_pos, b in enumerate(bits):
            sub |= ((i >> b) & 1) << (k - 1 - bit_pos)
        if sub == outcome_idx:
            new_amp.append(a * inv_sqrt_p)
        else:
            new_amp.append(0.0 + 0.0j)

    post = QuantumState(n, new_amp)
    return outcome_str, post


def sample(state: QuantumState, shots: int,
           rng: random.Random = None) -> dict:
    """
    Multi-shot sampling: measure all qubits `shots` times (without collapse
    — each shot starts from the same state).

    Returns {bitstring: count} histogram.
    """
    if rng is None:
        rng = random.Random()
    probs = state.probabilities()
    # Build CDF
    cdf = []
    cumulative = 0.0
    for p in probs:
        cumulative += p
        cdf.append(cumulative)
    cdf[-1] = 1.0  # ensure last bucket catches rounding

    counts = {}
    n = state.n
    for _ in range(shots):
        r = rng.random()
        lo, hi = 0, len(cdf) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cdf[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        outcome_str = format(lo, f"0{n}b")
        counts[outcome_str] = counts.get(outcome_str, 0) + 1

    return counts


def expectation_value(state: QuantumState, pauli: str, qubit: int) -> float:
    """
    Compute ⟨ψ|P_k|ψ⟩ where P ∈ {X, Y, Z, I} acts on `qubit`.

    Returns a real float in [-1, 1].
    """
    n = state.n
    bit = n - 1 - qubit
    mask = 1 << bit
    amp = state._amp

    if pauli == "I":
        return 1.0
    if pauli == "Z":
        result = 0.0
        for i, a in enumerate(amp):
            sign = -1.0 if (i >> bit) & 1 else 1.0
            result += sign * abs(a) ** 2
        return result
    if pauli == "X":
        result = 0.0 + 0.0j
        for i in range(state.dim):
            if (i >> bit) & 1:
                continue
            j = i | mask
            result += amp[i].conjugate() * amp[j] + amp[j].conjugate() * amp[i]
        return result.real
    if pauli == "Y":
        result = 0.0 + 0.0j
        for i in range(state.dim):
            if (i >> bit) & 1:
                continue
            j = i | mask
            result += -1j * amp[i].conjugate() * amp[j] + 1j * amp[j].conjugate() * amp[i]
        return result.real
    raise ValueError(f"Unknown Pauli operator: {pauli!r}. Use 'X', 'Y', 'Z', or 'I'")


def marginal_probabilities(state: QuantumState, qubits: list) -> dict:
    """
    Compute marginal probabilities for a subset of qubits (summing over all others).
    Returns {bitstring: probability} for the 2^k combinations.
    """
    n = state.n
    k = len(qubits)
    bits = [n - 1 - q for q in qubits]
    probs = {}
    for i, a in enumerate(state._amp):
        sub = 0
        for bit_pos, b in enumerate(bits):
            sub |= ((i >> b) & 1) << (k - 1 - bit_pos)
        key = format(sub, f"0{k}b")
        probs[key] = probs.get(key, 0.0) + abs(a) ** 2
    return probs


def state_fidelity(state1: QuantumState, state2: QuantumState) -> float:
    """F = |⟨ψ₁|ψ₂⟩|²"""
    return state1.fidelity(state2)
