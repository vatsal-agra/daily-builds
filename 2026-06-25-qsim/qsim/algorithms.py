"""
Quantum algorithm implementations.

Each algorithm is self-contained: it builds a Circuit, runs it, and returns
a structured result.  All outputs are verified against classical expectations.

Algorithms:
  1. Deutsch-Jozsa   — constant vs balanced oracle in 1 query (classical: 2^{n-1}+1)
  2. Bernstein-Vazirani — hidden bitstring in 1 query (classical: n)
  3. Grover's search — find marked items in O(√N) oracle calls
  4. Quantum Fourier Transform (QFT) — circuit for the exact DFT on 2^n points
  5. Quantum Teleportation — transmit 1-qubit state using 2 classical bits + 1 ebit
  6. Simon's Algorithm — find period in O(n) queries (classical: O(√2^n))
"""

import math
import cmath
import random
from .state import QuantumState
from .circuit import Circuit
from .gates import (
    GATES, Gate, Rx, Ry, Rz, Phase,
    apply_1q, apply_2q, apply_gate,
)
from .measure import measure, sample, measure_qubit

# Re-export the Hadamard matrix for convenience
_H = GATES["H"]
_X = GATES["X"]
_Z = GATES["Z"]
_CNOT = GATES["CNOT"]


# ------------------------------------------------------------------
# 1. Deutsch-Jozsa Algorithm
# ------------------------------------------------------------------

def deutsch_jozsa(n: int, oracle_type: str = "balanced",
                  secret_bits: str = None,
                  rng: random.Random = None) -> dict:
    """
    Deutsch-Jozsa algorithm: determine if an n-bit function f:{0,1}^n → {0,1}
    is CONSTANT (same output for all inputs) or BALANCED (0 for half, 1 for other).

    The algorithm uses ONE oracle query regardless of n.
    Classical worst case requires 2^(n-1)+1 queries.

    oracle_type: 'constant_0', 'constant_1', 'balanced', or 'balanced_parity'
                 'balanced' uses the parity function f(x) = x_0 ⊕ x_1 ⊕ … ⊕ x_{n-1}
    secret_bits: for 'balanced_parity', a string of 0/1 selecting which bits to XOR

    Returns {
        'result': 'constant' | 'balanced',
        'measurement': bitstring (all 0s → constant, otherwise → balanced),
        'circuit': Circuit,
        'verified': bool,  # True if result matches oracle_type
    }
    """
    if rng is None:
        rng = random.Random()

    # Build (n+1)-qubit circuit: n input qubits + 1 ancilla
    qc = Circuit(n + 1, n, name=f"Deutsch-Jozsa(n={n})")

    # Step 1: Put ancilla in |−⟩ = H|1⟩
    qc.x(n)        # ancilla to |1⟩
    for q in range(n + 1):
        qc.h(q)    # H on all qubits (input → |+⟩^n, ancilla → |−⟩)

    # Step 2: Apply oracle Uf
    if oracle_type in ("constant_0", "constant_zero"):
        pass  # f(x) = 0 → identity oracle
    elif oracle_type in ("constant_1", "constant_one"):
        # f(x) = 1 → flip ancilla for all inputs
        qc.x(n)   # global NOT on ancilla
    elif oracle_type == "balanced" or oracle_type == "balanced_parity":
        # f(x) = x_0 ⊕ x_1 ⊕ … (or selected bits via secret_bits)
        if secret_bits is None:
            # Default: XOR all input bits
            secret_bits = "1" * n
        for i, b in enumerate(secret_bits[:n]):
            if b == "1":
                qc.cnot(i, n)   # XOR qubit i into ancilla
    elif oracle_type == "balanced_phase":
        # Alternative balanced: phase kickback approach
        for i in range(n):
            qc.cnot(i, n)
    else:
        raise ValueError(f"Unknown oracle_type: {oracle_type!r}. "
                         f"Use 'constant_0', 'constant_1', 'balanced', "
                         f"'balanced_parity'")

    # Step 3: Hadamard on input qubits
    for q in range(n):
        qc.h(q)

    # Step 4: Measure input qubits
    for q in range(n):
        qc.measure(q, q)

    result = qc.run(shots=1, rng=rng)
    outcome = result.most_likely()[:n]

    # All 0s → constant; any 1 → balanced
    predicted = "constant" if outcome == "0" * n else "balanced"

    expected_type = (
        "constant" if oracle_type.startswith("constant") else "balanced"
    )
    verified = predicted == expected_type

    return {
        "result": predicted,
        "measurement": outcome,
        "circuit": qc,
        "verified": verified,
        "oracle": oracle_type,
    }


# ------------------------------------------------------------------
# 2. Bernstein-Vazirani Algorithm
# ------------------------------------------------------------------

def bernstein_vazirani(secret: str, rng: random.Random = None) -> dict:
    """
    Bernstein-Vazirani: recover a hidden n-bit string s in ONE oracle query.
    Oracle: f(x) = s·x = s_0 x_0 ⊕ s_1 x_1 ⊕ … (inner product mod 2)

    Classical algorithm requires n queries (one per bit).

    Returns {
        'result': recovered bitstring (should equal `secret`),
        'circuit': Circuit,
        'verified': bool,
    }
    """
    if rng is None:
        rng = random.Random()
    n = len(secret)
    if n < 1:
        raise ValueError("Secret must be non-empty")
    if not all(b in "01" for b in secret):
        raise ValueError("Secret must be a binary string")

    qc = Circuit(n + 1, n, name=f"Bernstein-Vazirani(n={n})")

    # Initialize ancilla to |−⟩
    qc.x(n)
    for q in range(n + 1):
        qc.h(q)

    # Oracle: for each 1 in secret, CNOT input[i] → ancilla
    for i, b in enumerate(secret):
        if b == "1":
            qc.cnot(i, n)

    # Hadamard on input qubits
    for q in range(n):
        qc.h(q)

    # Measure input qubits
    for q in range(n):
        qc.measure(q, q)

    result = qc.run(shots=1, rng=rng)
    recovered = result.most_likely()[:n]

    return {
        "result": recovered,
        "circuit": qc,
        "verified": recovered == secret,
        "secret": secret,
    }


# ------------------------------------------------------------------
# 3. Grover's Search Algorithm
# ------------------------------------------------------------------

def grover(n: int, marked: list = None, rng: random.Random = None) -> dict:
    """
    Grover's algorithm: find a marked item among 2^n items in O(√2^n) oracle calls.
    Classical search requires O(2^n) calls on average.

    marked: list of integer indices to mark (default: [0]).
            Multiple targets are supported (algorithm scales with √(2^n/k)
            where k = number of marked items).

    Returns {
        'result': most likely measured outcome (bitstring),
        'result_int': int value of result,
        'marked': list of marked items,
        'iterations': number of Grover iterations used,
        'success_prob': probability of correct answer,
        'counts': shot histogram,
        'circuit': Circuit,
        'verified': bool,  # True if result is in marked
    }
    """
    if rng is None:
        rng = random.Random()
    if marked is None:
        marked = [0]
    N = 1 << n
    for m in marked:
        if not (0 <= m < N):
            raise ValueError(f"Marked item {m} out of range [0, {N})")
    k = len(marked)

    # Optimal number of iterations: ⌊(π/4) √(N/k)⌋
    iterations = max(1, round(math.pi / 4 * math.sqrt(N / k)))

    qc = Circuit(n, n, name=f"Grover(n={n}, targets={marked})")

    # Initialize: uniform superposition
    for q in range(n):
        qc.h(q)

    for _ in range(iterations):
        # Oracle: mark the target states (flip phase)
        _grover_oracle(qc, n, marked)
        # Diffusion (Grover diffusion = 2|+⟩⟨+| - I)
        _grover_diffusion(qc, n)

    for q in range(n):
        qc.measure(q, q)

    shots = 512
    result = qc.run(shots=shots, rng=rng)
    outcome = result.most_likely()
    outcome_int = int(outcome, 2)

    # Theoretical success probability after `iterations` steps
    theta = math.asin(math.sqrt(k / N))
    success_prob = math.sin((2 * iterations + 1) * theta) ** 2

    return {
        "result": outcome,
        "result_int": outcome_int,
        "marked": marked,
        "iterations": iterations,
        "success_prob": success_prob,
        "counts": result.counts,
        "circuit": qc,
        "verified": outcome_int in marked,
    }


def _grover_oracle(qc: Circuit, n: int, marked: list):
    """
    Phase oracle: flip the sign of all marked basis states.
    Uses a multi-controlled Z gate decomposed into Toffoli + single-qubit gates.
    """
    for target_idx in marked:
        target_bits = format(target_idx, f"0{n}b")
        # Flip qubits where the target has a 0 (so the all-|1⟩ state corresponds
        # to the target)
        for i, b in enumerate(target_bits):
            if b == "0":
                qc.x(i)
        # Multi-controlled Z (decomposed as H + multi-controlled X + H on last qubit)
        if n == 1:
            qc.z(0)
        elif n == 2:
            qc.cz(0, 1)
        else:
            # Decompose n-controlled Z into CZ + Toffoli chain
            _multi_ctrl_z(qc, list(range(n)))
        # Unflip
        for i, b in enumerate(target_bits):
            if b == "0":
                qc.x(i)


def _multi_ctrl_z(qc: Circuit, qubits: list):
    """
    n-controlled Z using repeated Toffoli decomposition.
    Requires no ancilla — works directly for small n using the identity:
    n-CCZ = H on target + n-CCX + H on target.
    """
    n = len(qubits)
    target = qubits[-1]
    controls = qubits[:-1]

    qc.h(target)
    _multi_ctrl_x(qc, controls, target)
    qc.h(target)


def _multi_ctrl_x(qc: Circuit, controls: list, target: int):
    """
    Multi-controlled NOT using Toffoli decomposition.
    Uses V (√X) decomposition for controls > 2 (ancilla-free).
    """
    nc = len(controls)
    if nc == 0:
        qc.x(target)
    elif nc == 1:
        qc.cnot(controls[0], target)
    elif nc == 2:
        qc.ccx(controls[0], controls[1], target)
    else:
        # Lemma 7.5 (Nielsen & Chuang): ancilla-free decomposition
        # Use the recursive unary approach with √X
        # For simplicity, use the Toffoli chain with the target as ancilla
        # (works for n ≥ 3 without extra ancilla using a phase trick)
        _rcccx(qc, controls, target)


def _rcccx(qc: Circuit, controls: list, target: int):
    """Recursive ancilla-free n-controlled X (using phase-kickback technique)."""
    nc = len(controls)
    if nc == 0:
        qc.x(target)
        return
    if nc == 1:
        qc.cnot(controls[0], target)
        return
    if nc == 2:
        qc.ccx(controls[0], controls[1], target)
        return

    # For nc ≥ 3: build the nc-controlled-X by wrapping controlled() nc times.
    # controlled(X)            = C1-X  (2-qubit gate)
    # controlled(C1-X)         = C1-C1-X  (3-qubit gate)
    # …
    # After nc wraps → nc-controlled-X (nc+1-qubit gate)
    from .gates import controlled
    c_gate = GATES["X"]
    for _ in range(nc):
        c_gate = controlled(c_gate)
    qc.gate(c_gate, controls + [target])


def _grover_diffusion(qc: Circuit, n: int):
    """
    Grover diffusion operator: 2|+⟩⟨+| - I
    = H^n (2|0⟩⟨0| - I) H^n
    """
    for q in range(n):
        qc.h(q)
        qc.x(q)
    # Multi-controlled Z on all n qubits (implements 2|0⟩⟨0|-I after the X's)
    if n == 1:
        qc.z(0)
    elif n == 2:
        qc.cz(0, 1)
    else:
        _multi_ctrl_z(qc, list(range(n)))
    for q in range(n):
        qc.x(q)
        qc.h(q)


# ------------------------------------------------------------------
# 4. Quantum Fourier Transform
# ------------------------------------------------------------------

def qft_circuit(n: int, inverse: bool = False) -> Circuit:
    """
    Build the QFT (or inverse QFT) circuit on n qubits.

    QFT: |x⟩ → (1/√2^n) Σ_{k=0}^{2^n-1} e^{2πixk/2^n} |k⟩

    The standard textbook circuit uses Hadamard + controlled-R_k gates.

    Returns the Circuit (without measurement).
    """
    qc = Circuit(n, name=f"{'IQFT' if inverse else 'QFT'}(n={n})")

    if not inverse:
        for i in range(n):
            qc.h(i)
            for j in range(i + 1, n):
                angle = 2 * math.pi / (1 << (j - i + 1))
                qc.cp(angle, j, i)
        # Swap to get the standard bit order
        for i in range(n // 2):
            qc.swap(i, n - 1 - i)
    else:
        # Inverse QFT: reverse operations
        for i in range(n // 2):
            qc.swap(i, n - 1 - i)
        for i in range(n - 1, -1, -1):
            for j in range(n - 1, i, -1):
                angle = -2 * math.pi / (1 << (j - i + 1))
                qc.cp(angle, j, i)
            qc.h(i)

    return qc


def verify_qft(n: int, rng: random.Random = None) -> dict:
    """
    Verify the QFT circuit against the exact DFT matrix.

    Applies the QFT circuit to each computational basis state |x⟩
    and checks that the output amplitudes match (1/√N) e^{2πixk/N}.

    Returns {
        'max_error': float,  # maximum amplitude error across all basis states
        'verified': bool,    # True if max_error < 1e-8
        'n': int,
        'N': int,
    }
    """
    if rng is None:
        rng = random.Random()
    N = 1 << n
    qc = qft_circuit(n)
    max_err = 0.0

    for x in range(N):
        init = QuantumState.from_basis(n, x)
        result = qc.run(initial_state=init, shots=1, rng=rng)
        state = result.final_state
        for k in range(N):
            expected = cmath.exp(2j * math.pi * x * k / N) / math.sqrt(N)
            err = abs(state._amp[k] - expected)
            if err > max_err:
                max_err = err

    return {
        "max_error": max_err,
        "verified": max_err < 1e-8,
        "n": n,
        "N": N,
    }


def quantum_phase_estimation(n_count: int, unitary_eigenphase: float,
                              rng: random.Random = None) -> dict:
    """
    Quantum Phase Estimation: estimate the phase φ such that U|u⟩ = e^{2πiφ}|u⟩.

    For demonstration: uses a 1-qubit unitary U = P(2πφ) (phase gate),
    whose eigenstate |1⟩ has eigenvalue e^{2πiφ}.

    n_count: number of counting qubits (precision = 1/2^n_count)

    Returns {
        'estimated_phase': float in [0, 1),
        'true_phase': float,
        'error': float,
        'circuit': Circuit,
        'verified': bool,
    }
    """
    if rng is None:
        rng = random.Random()
    n = n_count + 1  # n_count counting qubits + 1 eigenstate qubit
    phase = unitary_eigenphase % 1.0

    qc = Circuit(n, n_count, name=f"QPE(n={n_count}, φ={phase:.4f})")

    # Prepare eigenstate |1⟩ on last qubit
    qc.x(n_count)

    # Apply H to counting qubits
    for q in range(n_count):
        qc.h(q)

    # Controlled-U^(2^k) gates: controlled-P(2π·φ·2^k) on target qubit
    for k in range(n_count):
        angle = 2 * math.pi * phase * (1 << (n_count - 1 - k))
        qc.cp(angle, k, n_count)

    # Inverse QFT on counting qubits (without the final SWAP correction)
    iqft = qft_circuit(n_count, inverse=True)
    for instr in iqft._instructions:
        if instr.kind == "gate":
            qc._gate(instr.gate, instr.qubits)

    # Measure counting qubits
    for q in range(n_count):
        qc.measure(q, q)

    shots = 256
    result = qc.run(shots=shots, rng=rng)
    top = result.most_likely()[:n_count]
    estimated_int = int(top, 2)
    estimated_phase = estimated_int / (1 << n_count)
    error = abs(estimated_phase - phase)

    return {
        "estimated_phase": estimated_phase,
        "true_phase": phase,
        "error": error,
        "measurement": top,
        "counts": result.counts,
        "circuit": qc,
        "verified": error < 1.0 / (1 << n_count),  # within 1 LSB
    }


# ------------------------------------------------------------------
# 5. Quantum Teleportation
# ------------------------------------------------------------------

def teleportation(psi: QuantumState = None, rng: random.Random = None) -> dict:
    """
    Teleport an arbitrary 1-qubit state |ψ⟩ from Alice to Bob using:
    - 1 shared Bell pair (ebit)
    - 2 classical bits communicated from Alice to Bob

    The final state of Bob's qubit should equal the original |ψ⟩.

    psi: a 1-qubit QuantumState to teleport (default: (|0⟩+i|1⟩)/√2)

    Returns {
        'fidelity': float,  # |⟨ψ|result⟩|² — should be 1.0
        'classical_bits': (m0, m1),
        'verified': bool,
    }
    """
    if rng is None:
        rng = random.Random()
    if psi is None:
        # Default: (|0⟩ + i|1⟩)/√2  — neither a real nor standard state
        psi = QuantumState(1, [1.0/math.sqrt(2), 1j/math.sqrt(2)])

    if psi.n != 1:
        raise ValueError("Teleportation requires a 1-qubit state")

    # 3-qubit system: [Alice's qubit (0), Alice's Bell (1), Bob's Bell (2)]
    # Start in |ψ⟩ ⊗ |00⟩
    initial = QuantumState.tensor_product(psi, QuantumState.zero(2))

    # Prepare Bell pair between qubits 1 and 2
    state = initial
    state = apply_1q(state, _H, 1)
    state = apply_2q(state, _CNOT, 1, 2)

    # Alice's Bell measurement: CNOT(0→1) then H(0)
    state = apply_2q(state, _CNOT, 0, 1)
    state = apply_1q(state, _H, 0)

    # Measure qubits 0 and 1 (Alice's bits)
    m0, state = measure_qubit(state, 0, rng)
    m1, state = measure_qubit(state, 1, rng)

    # Bob applies corrections based on classical bits
    if m1 == 1:
        state = apply_1q(state, _X, 2)
    if m0 == 1:
        state = apply_1q(state, _Z, 2)

    # Extract Bob's qubit (qubit 2) reduced state and check fidelity
    # Bob's qubit is now in a product state with qubits 0,1 (which are measured)
    # We compare Bob's marginal state to the original |ψ⟩

    # Compute fidelity by tracing out qubits 0 and 1
    # Since qubits 0,1 are measured and collapsed, we can just look at
    # the amplitudes conditioned on the measurement outcomes
    n_tot = 3
    # Non-zero amplitudes should only be for indices where qubit0=m0, qubit1=m1
    mask0 = 1 << (n_tot - 1 - 0)  # qubit 0's bit in the full index
    mask1 = 1 << (n_tot - 1 - 1)  # qubit 1's bit
    mask2 = 1 << (n_tot - 1 - 2)  # qubit 2's bit

    # Extract Bob's amplitudes for qubit2=0 and qubit2=1
    a0 = state._amp[(m0 << 2) | (m1 << 1) | 0]  # qubit2=0
    a1 = state._amp[(m0 << 2) | (m1 << 1) | 1]  # qubit2=1
    norm = math.sqrt(abs(a0)**2 + abs(a1)**2)
    if norm > 1e-10:
        a0, a1 = a0 / norm, a1 / norm
    bob_state = QuantumState(1, [a0, a1])

    fidelity = bob_state.fidelity(psi)

    return {
        "fidelity": fidelity,
        "classical_bits": (m0, m1),
        "bob_state": bob_state,
        "original_state": psi,
        "verified": fidelity > 0.9999,
    }


# ------------------------------------------------------------------
# 6. Simon's Algorithm
# ------------------------------------------------------------------

def simon(n: int, period: str = None, rng: random.Random = None) -> dict:
    """
    Simon's algorithm: find the period s of a function f:{0,1}^n → {0,1}^n
    such that f(x) = f(x⊕s) for all x.

    Uses O(n) quantum queries; classical requires O(2^{n/2}) queries.

    period: n-bit string (default: random non-zero period)

    Returns {
        'period': str (found period),
        'true_period': str,
        'verified': bool,
        'samples': list of measurement strings,
        'queries': number of quantum circuit runs,
    }
    """
    if rng is None:
        rng = random.Random()
    if period is None:
        # Random non-zero period
        period = format(rng.randint(1, (1 << n) - 1), f"0{n}b")

    s = int(period, 2)

    # Oracle for f with period s: f(x) = x if the MSB of x⊕s is 0, else x⊕s
    # Standard "hiding" oracle: f(x) = x & ~s (collapses x and x⊕s to same image)
    def oracle_func(x: int) -> int:
        """f(x) = x if (x < x⊕s) else (x⊕s) — gives a valid 2-to-1 function."""
        xored = x ^ s
        return min(x, xored)

    samples = []
    queries = 0
    needed = n - 1  # We need n-1 linearly independent samples to solve the system

    # Each circuit run gives one string y with y·s = 0 (mod 2)
    for _ in range(n + 10):  # extra runs to ensure enough samples
        qc = Circuit(2 * n, n, name=f"Simon(n={n})")

        # Uniform superposition on first n qubits
        for q in range(n):
            qc.h(q)

        # Oracle: uses XOR-based construction
        # We build the oracle matrix directly as a permutation
        _simon_oracle(qc, n, oracle_func)

        # Hadamard on first n qubits
        for q in range(n):
            qc.h(q)

        # Measure first n qubits
        for q in range(n):
            qc.measure(q, q)

        result = qc.run(shots=1, rng=rng)
        y = result.most_likely()[:n]
        queries += 1

        # y must satisfy y·s = 0 mod 2
        dot = sum(int(a) * int(b) for a, b in zip(y, period)) % 2
        if dot == 0 and y not in samples:
            samples.append(y)

        if len(samples) >= needed:
            break

    # Solve the linear system over GF(2) to find s
    found_period = _gf2_solve(samples, n)

    return {
        "period": found_period,
        "true_period": period,
        "verified": found_period == period,
        "samples": samples,
        "queries": queries,
    }


def _simon_oracle(qc: Circuit, n: int, func):
    """
    Implement the oracle |x⟩|y⟩ → |x⟩|y⊕f(x)⟩.
    Uses a custom gate built from the function's truth table.
    """
    # Build the full 2^(2n) × 2^(2n) permutation matrix
    N = 1 << n
    dim = 1 << (2 * n)
    mat = [0.0 + 0.0j] * (dim * dim)

    for x in range(N):
        fx = func(x)
        for y in range(N):
            inp = (x << n) | y
            out = (x << n) | (y ^ fx)
            mat[out * dim + inp] = 1.0 + 0.0j

    from .gates import Gate, apply_gate
    oracle_gate = Gate(f"Simon_Oracle", mat, 2 * n)
    qc.gate(oracle_gate, list(range(2 * n)))


def _gf2_solve(samples: list, n: int) -> str:
    """
    Solve Ay = 0 over GF(2) to find the null space vector y ≠ 0.
    A has rows from `samples`, each a bitstring.

    Returns the found period string, or '0'*n if no unique solution.
    """
    if not samples:
        return "0" * n

    # Build matrix over GF(2)
    M = [[int(b) for b in row] for row in samples]
    rows = len(M)
    # Gaussian elimination
    pivot_cols = []
    col = 0
    for row in range(rows):
        # Find pivot in column col
        while col < n:
            found = -1
            for r in range(row, rows):
                if M[r][col] == 1:
                    found = r
                    break
            if found >= 0:
                M[row], M[found] = M[found], M[row]
                pivot_cols.append(col)
                for r in range(rows):
                    if r != row and M[r][col] == 1:
                        M[r] = [(M[r][c] ^ M[row][c]) for c in range(n)]
                col += 1
                break
            else:
                col += 1

    # Find free variables (non-pivot columns)
    free_cols = [c for c in range(n) if c not in pivot_cols]
    if not free_cols:
        return "0" * n  # trivial period only

    # Set the first free variable to 1, others to 0
    sol = [0] * n
    sol[free_cols[0]] = 1
    for i, pc in enumerate(pivot_cols):
        if i < len(M):
            sol[pc] = M[i][free_cols[0]]

    return "".join(str(b) for b in sol)


# Expose the H gate matrix for testing
def H_gate_matrix():
    """Return the 2x2 Hadamard matrix as a flat list."""
    _S = 1.0 / math.sqrt(2)
    return [_S, _S, _S, -_S]
