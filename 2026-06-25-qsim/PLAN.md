# QSim — Quantum Circuit Simulator

## Concept
A complete quantum circuit simulator built from scratch in pure Python.
Quantum computing operates on *qubits* — two-level quantum systems whose
state is a complex-valued superposition over all 2^n basis states at once.
Unitary gates rotate this high-dimensional state vector; measurement
collapses it probabilistically according to the Born rule.

This is intellectually fascinating because:
- You can demonstrate genuine quantum speedup (Grover's √N vs classical N)
- The math is concrete linear algebra over ℂ, verifiable by hand
- Algorithms like QFT underlie real-world things (Shor's algorithm, phase estimation)
- The state space grows exponentially — simulating 30 qubits needs 16 GB of RAM,
  which means no classical computer can brute-force large quantum circuits

## Why interesting today
Nothing in this ledger touches quantum computing. The mathematics — tensor
products of Hilbert spaces, unitary evolution, Born-rule measurement — is
completely different from physics engines, language VMs, or path tracers.
It's also immediately educational: every feature has a "why" rooted in physics.

## Architecture
```
2026-06-25-qsim/
  qsim/
    state.py         State vector: n complex amplitudes, Dirac notation printer
    gates.py         Gate library: matrices + efficient O(2^n) applicators
    circuit.py       Circuit builder + execution engine
    measure.py       Born-rule measurement, partial measurement, expectation values
    algorithms.py    Grover, Deutsch-Jozsa, QFT, Bernstein-Vazirani, teleportation
    noise.py         Monte Carlo noise: depolarizing, bit-flip, phase-flip (stretch)
    visualize.py     ASCII circuit diagram + HTML interactive visualizer
    cli.py           Argument-parsed CLI with subcommands
  tests/
    test_gates.py
    test_measure.py
    test_algorithms.py
    test_noise.py
    test_visualize.py
  demo.sh
  PLAN.md
  REVIEW.md
  README.md
```

## Key algorithmic insight: O(2^n) gate application
Rather than multiplying the full 2^n × 2^n unitary matrix by the state
vector (O(4^n) work), we exploit gate sparsity:

**1-qubit gate** on qubit k (matrix [[a,b],[c,d]]):
  For each of the 2^(n-1) index pairs (i₀, i₁) differing only in bit k:
    new[i₀] = a·old[i₀] + b·old[i₁]
    new[i₁] = c·old[i₀] + d·old[i₁]

**2-qubit gate** on qubits (c, t):
  For each of the 2^(n-2) index quadruples:
    Apply the 4×4 unitary to the 4 amplitudes (00, 01, 10, 11)

This is O(2^n) per gate — 1000× faster than naive matrix multiply for 10 qubits,
and the only viable approach for 20+ qubits.

## Feature List

### Required (4)
1. **State vector engine** — n-qubit complex state vector (up to ~20 qubits
   in reasonable time via the O(2^n) gate applicator), norm tracking,
   Dirac notation pretty-printer (shows significant terms), inner product,
   tensor product of states, Schmidt decomposition for 2-qubit subsystems.

2. **Complete gate library** — Single-qubit: H, X, Y, Z, S, T, Sdg, Tdg,
   Phase(θ), Rx(θ), Ry(θ), Rz(θ), U(θ,φ,λ) (IBM-style general gate).
   Two-qubit: CNOT, CZ, SWAP, iSWAP, controlled-Phase(θ), controlled-U.
   Three-qubit: Toffoli (CCX), Fredkin (CSWAP). Custom unitary (user-supplied matrix).
   All gates verified: U†U = I (unitarity check), correct action on basis states.

3. **Quantum algorithms** — All implemented as circuits, all output verified:
   - Deutsch-Jozsa: classifies n-bit oracles as constant/balanced in 1 query
     (classical needs 2^(n-1)+1 in the worst case)
   - Grover's algorithm: searches an unstructured database of 2^n items with
     optimal ⌊π√2^n/4⌋ iterations; reports correct item + probability
   - Quantum Fourier Transform: exact n-qubit QFT circuit verified against
     the DFT matrix
   - Bernstein-Vazirani: recovers a hidden n-bit string in 1 query (classical
     needs n queries)
   - Quantum teleportation: teleports an arbitrary single-qubit state via
     2 classical bits + 1 ebit

4. **Measurement** — Born-rule single-shot measurement (collapse + post-state),
   multi-shot sampling returning a histogram of outcomes, partial measurement
   of a subset of qubits (correct marginal probabilities + conditional collapse),
   expectation value ⟨ψ|O|ψ⟩ for Pauli operators, fidelity between states.

### Stretch (3)
5. **Monte Carlo noise model** — Bit-flip, phase-flip, and depolarizing channels
   as Kraus operators applied randomly after each gate (per-qubit error rate p).
   Multi-shot simulation accumulates the noisy distribution. Also: T1/T2
   amplitude/phase damping channels.

6. **ASCII circuit diagram** — Renders the circuit as text: qubit wires,
   gate boxes, two-qubit connections with vertical lines, measurement meters.

7. **Interactive HTML visualizer** — Single-file self-contained HTML that shows:
   - Rendered circuit diagram (SVG)
   - Amplitude histogram (|⟨x|ψ⟩|² for each basis state, color-coded phase)
   - Bloch sphere for single-qubit reduced states (SVG)
   - Shot histogram after multi-shot measurement
   - Step-through mode: apply gates one by one and watch the state evolve

## Implementation notes
- Pure Python 3 stdlib only (complex arithmetic is built-in)
- complex type uses `complex(re, im)` or `re + im*1j`
- State vector: `list[complex]` of length 2^n
- For 20 qubits: 2^20 = 1,048,576 complex numbers ≈ 16 MB — fine
- Gate application: O(2^n) bitwise pairing — fast enough for ≤20 qubits
- All random sampling via `random.random()` (seeded for reproducibility)
- ASCII art circuit: character grid, rendered with box-drawing characters
- HTML visualizer: inline SVG + CSS, no external dependencies
