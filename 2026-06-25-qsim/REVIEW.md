# Phase 3 — Adversarial Review

## What I attacked

After building the core engine, I systematically attacked my own work as a hostile
reviewer looking for physics bugs, iteration-count errors, unsafe inputs, and UX failures.

## Issues Found and Fixed

### 1. CRITICAL: Grover iteration count overshoots for small n

**Problem:** The Grover oracle-call count used `round(π/4 · √(N/k))` instead of the
exact formula `floor(π / (4 · arcsin(√(k/N))))`. For n=2, k=1:
- `round(π/2) = 2` → 2 iterations → P(success) = **25%** (overshoot!)
- `floor(π/(4·π/6)) = 1` → 1 iteration → P(success) = **100%** ✓

The approximation `π/4·√(N/k)` diverges from the exact formula precisely where N
is small (n=2,3) because arcsin(x) ≠ x for large x.

**Effect:** Grover n=2 target=1 returned item 0 (wrong answer).

**Fix:** Changed to `theta = math.asin(math.sqrt(k/N)); iterations = max(1, math.floor(math.pi / (4*theta)))`.
All 4 n=2 targets now achieve 100% success probability. All n=3..5 targets still verified.

**Regression:** `grover(2, [t])` for all t ∈ {0,1,2,3} now returns correct items with P=1.0.

---

### 2. MODERATE: Simon's algorithm accepted invalid all-zeros period

**Problem:** Simon requires a non-zero period s ≠ 0 (otherwise f is injective and
Simon's algorithm is undefined). Passing all-zeros silently produced a spurious result.
Also, period length mismatches (e.g. n=2, period='000' of 3 bits) were not caught.

**Fix:** Added validation:
- `period length != n` → `ValueError`
- non-binary characters → `ValueError`
- all-zeros period → `ValueError` with explanation

---

### 3. MINOR: QPE displayed confusing raw phase vs mod-1 phase

**Problem:** `qpe 1.5` showed "True phase: φ = 1.500000" but "estimated φ̂ = 0.500000"
because QPE internally uses `phase % 1.0`. The mismatch looks like a wrong answer.

**Fix:** CLI now shows "Input phase: 1.500000 (mod 1 → 0.500000)" and uses the
normalized phase for both the display and the computation.

---

### 4. MINOR: HTML visualizer — unescaped `}` in f-string

**Problem:** JavaScript template literal in the HTML f-string had:
```
lbl.textContent = `q${bv.q} (x=${bv.x.toFixed(2)}, y=...)`
```
Inside a Python f-string, the `}` after `toFixed(2)` before `, y=` is a single
unescaped closing brace → `SyntaxError: f-string: single '}' is not allowed`.

**Fix:** Replaced with string concatenation (no template literal in that line).

---

## Issues Found That Were Already Correct

The following were explicitly verified during Phase 3 and found to be correct:

- **HH = I**: Hadamard is self-inverse to floating-point precision (1e-16)
- **CNOT truth table**: All 4 inputs verified including reversed qubit order
- **Toffoli truth table**: All 8 inputs verified; `controlled(controlled(X)) == Toffoli`
- **Fredkin truth table**: Ctrl=0 is identity; Ctrl=1 swaps correctly
- **QFT×IQFT = I**: For n=2,3,4 — max error < 5e-16
- **iSWAP**: |01⟩ → i|10⟩ ✓
- **Bell state entanglement entropy**: Exactly log(2) ✓
- **Bell measurement correlation**: 200 trials always correlated ✓
- **Teleportation fidelity**: 30 trials with |1⟩, all fidelity > 0.9999 ✓
- **Partial measurement collapse**: 200 Bell trials, post-state always consistent ✓
- **Expectation values**: ⟨Z⟩|0⟩=1, ⟨Z⟩|1⟩=-1, ⟨X⟩|+⟩=1 ✓
- **Gate unitarity**: All 21 standard gates pass U†U=I ✓
- **Norm conservation**: Random gate sequences preserve norm to 1e-10 ✓
- **CZ/SWAP symmetry**: Both symmetric under qubit-order swap ✓
- **Rx(π)|0⟩ = -i|1⟩**: Correct rotation ✓
- **Rx(2π) = -I**: Global phase correct ✓
- **Noise channels**: Depolarizing, bit-flip, amplitude damping verified against theory ✓

## Tests After All Fixes

```
demo --seed 42:  7/7 algorithms verified ✓
Grover n=2: all 4 targets P=1.0 ✓
Grover n=3: all 8 targets ✓
Grover n=4,5: verified ✓
QFT n=2,3,4: max_error < 1e-14 ✓
QPE all representable phases: error = 0 ✓
Teleportation: fidelity = 1.0 (30 trials) ✓
```
