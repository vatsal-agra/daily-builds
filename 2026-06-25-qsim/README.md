# qsim — Pure-Python Quantum Circuit Simulator

A full quantum circuit simulator built from scratch: complex state vectors,
unitary gates, Born-rule measurement, noise channels, and seven quantum
algorithms — all in pure Python 3, zero dependencies.

## Quick start

```bash
cd 2026-06-25-qsim
python qsim_cli.py demo --seed 42       # 7/7 algorithms verified
python qsim_cli.py grover 4 7           # Grover search on 4 qubits, target index 7
python qsim_cli.py qft 3                # QFT on 3 qubits
python qsim_cli.py bell --shots 1000    # Bell state entanglement
python qsim_cli.py noise --p 0.05       # Noisy Bell circuit
python qsim_cli.py viz                  # Write interactive HTML visualizer
```

## Architecture

```
qsim/
  state.py        QuantumState: 2^n complex amplitudes, entanglement entropy
  gates.py        21 standard gates + Rx/Ry/Rz/Phase/U, controlled(), apply_*()
  circuit.py      Circuit builder with fluent API, shot-level noise injection
  measure.py      Full/partial collapse, sampling, expectation values
  noise.py        Kraus-operator noise channels: bit-flip, depolarizing, T1/T2
  algorithms.py   7 quantum algorithms implemented from gate primitives
  visualize.py    ASCII art + self-contained interactive HTML with SVG+Bloch
  cli.py          Subcommand CLI for all features
```

### Gate application — O(2^n) not O(4^n)

For a 1-qubit gate on qubit `q` in an `n`-qubit system, pair each amplitude
`|...0...⟩` with `|...1...⟩` (differ only at bit `q`) and apply the 2×2 matrix.
Only 2^(n-1) pairs exist, so one gate application is O(2^n), not O(4^n).

### Noise model — quantum trajectory method

Rather than tracking a 4^n density matrix, the noise model applies a random
Kraus operator to the state vector once per shot. This keeps memory at O(2^n)
and gives statistically correct shot histograms.

## Algorithms

| Command | Algorithm | What it demonstrates |
|---------|-----------|----------------------|
| `deutsch-jozsa` | Deutsch-Jozsa | Constant vs balanced oracle in 1 query |
| `bernstein-vazirani` | Bernstein-Vazirani | Hidden bit-string in 1 query |
| `grover N T...` | Grover search | Quadratic speedup; exact iteration formula |
| `qft N` | Quantum Fourier Transform | QFT × IQFT = I verified |
| `qpe PHASE` | Quantum Phase Estimation | Estimates eigenphase of a unitary |
| `teleport` | Quantum Teleportation | Fidelity 1.0 via Bell pair + classical bits |
| `simon N PERIOD` | Simon's algorithm | Exponential speedup for period finding |
| `bell` | Bell states | Entanglement entropy = log(2) |

## Grover's iteration count

The correct formula is `floor(π / (4·arcsin(√(k/N))))`, not the common
approximation `round(π/4·√(N/k))`. For n=2 (N=4, k=1), the approximation
gives 2 iterations → 25% success; the exact formula gives 1 → 100% success.

## Build log

| Phase | Status | Notes |
|-------|--------|-------|
| 1 — Plan | ✓ | Architecture, algorithm list, PLAN.md |
| 2 — Core build | ✓ | All 7 algorithms, noise, visualizer, CLI |
| 3 — Adversarial review | ✓ | 4 bugs found and fixed (see REVIEW.md) |
| 4 — Stretch + Polish | ✓ | QKD demo, circuit comparison, enhanced CLI |
| 5 — Verification | ✓ | Full test suite, all green |
| 6 — Ship | ✓ | Committed, pushed |
