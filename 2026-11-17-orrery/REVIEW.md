# REVIEW — adversarial pass (Phase 3)

Method: drove the CLI with hostile input (bad flags, malformed/empty/coincident scenarios, absurd step counts,
chaotic systems with fixed steps), read the HTML in a headless browser, and re-read the numerics for edge cases.

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| R1 | `-n 1` / `-n -5` silently replaced by the default (200/300) instead of failing | medium | explicit invalid n is now an error; only n=0 means "default" |
| R2 | Two bodies at the same point (zero softening) gave `E0=-Inf`, NaN diagnostics and a late "non-finite" error | high | `Validate` rejects coincident bodies when ε=0 with a message naming both |
| R3 | Fixed-step run on the Pythagorean problem returned **ΔE/E₀ = 718** with exit 0 and no warning — silent garbage | high | `run`/`bench` print a loud warning when energy error > 1% and suggest `dopri5` or a smaller dt |
| R4 | `-tol -1` or `-tol 0` silently ignored and replaced by 1e-10 | low | non-positive/NaN `-tol` is rejected |
| R5 | `bh` on tiny systems printed `0s` timings and `0.0x` speedup (timer resolution, single shot) | medium | timings repeat until ≥20 ms; speedup shown as `n/a` when unmeasurable; needs N ≥ 2 |
| R6 | Solar-system report: inner planets collapsed into one blob at default zoom (Neptune sets the scale) | medium | viewer auto-enables √-radius scaling when body radii span >8×; toggle stays |
| R7 | Chart x-axis last tick label clipped at the right edge | low | last label right-aligned |
| R8 | Canvases had no accessible name; hover readout not discoverable | low | `role="img"` + `aria-label`, readout in `aria-live` region |
| R9 | Generators accepted unbounded `-n` (1e6 bodies → O(N²) diagnostics = hang) | medium | n capped at 20000 with an explanatory error |
| R10 | Scenario file with a UTF-8 BOM failed with `unknown directive "﻿title"` | low | BOM stripped |
| R11 | Wisdom–Holman is only accurate when body 0 dominates: on the 2:1 binary it is *worse* than leapfrog (ΔE 2.7e-3 vs 1e-3) | doc | not a bug (the Hamiltonian split error scales with m/m₀); documented in README, `wh` rejects bodies heavier than body 0, covered by a test that WH wins on the solar system |
| R12 | Barnes–Hut breaks Newton's 3rd law so momentum drifts ~1e-4 on a Plummer sphere | doc | inherent to tree codes; documented; `-theta 0` is exact |
| R13 | `#` inside a `title` line truncates the title (comment stripping) | doc | documented in the DSL comment |
| R14 | Barnes–Hut was *slower* than direct summation at N=2000 and for small θ (leaf slices allocated per cell, wide node structs, per-target far-field test did the cell-containment check first) | medium | leaves now use an allocation-free linked list, compact nodes with cached size², cheap far-field test first, targets walked in tree order. 1.6× faster at identical error. Honest remaining limit: monopole-only tree cost grows ~θ⁻³, break-even with direct is θ≈0.3 at N=20 000 — documented in README |
| R15 | (found while building the order study) measuring error at exactly one period made symplectic Euler look 2nd-order: its O(h) error is a time shift that closes on itself after a full period | high (wrong science) | study now ends at 1.37 periods; experiment kept as a comment in `MeasureOrder`; test asserts every method matches its nominal order |
| R16 | (found while building the Lyapunov estimator) a regular Kepler orbit was labelled "chaotic"/"transient" because shear alone produces ~ln(ωT) ≈ 6–9 apparent e-folds | high (wrong science) | verdict now rests on e-folds in the second half (≥8 chaotic, <3 regular) with a 15-e-fold bar for "transient chaos"; tests assert Kepler=regular, 16-body Plummer=chaotic |

All items except the three "doc" ones are fixed in this phase; fix verification is part of the test-suite (Phase 5).
