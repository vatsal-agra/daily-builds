# Orrery — PLAN

## Concept
A from-scratch **N-body gravity laboratory** in Go (stdlib only). Define a system of masses, integrate it with a
family of integrators, and *measure* how well each one preserves the physics: energy, momentum, angular momentum,
convergence order, time-reversibility. Includes a Barnes–Hut tree for large N, an exact Kepler solver used as an
oracle, and a self-contained HTML viewer/report. This repo has no orbital-mechanics / N-body build yet.

## Why it's interesting
Naive integrators (Euler, even RK4) spiral planets away; symplectic ones (leapfrog, Yoshida) keep energy error
bounded forever. Seeing that, with numbers and plots, from code written from scratch, is the point. The figure-eight
three-body choreography and Plummer-sphere virial equilibrium give strong, non-trivial correctness checks.

## Architecture
- `orrery/` library
  - `vec.go` — Vec3 math
  - `system.go` — Body, System, energies, momentum, COM, angular momentum
  - `force.go` — direct O(N²) accelerations (softened) + Barnes–Hut octree accelerations
  - `integrate.go` — Euler, SymplecticEuler, Leapfrog (KDK), Yoshida4, RK4, DOPRI5 (adaptive), Wisdom–Holman-style Kepler-drift
  - `kepler.go` — Kepler equation solver, universal-variable two-body propagation, state ⇄ orbital elements
  - `scenario.go` — text scenario DSL parser + generators (two-body, solar system, figure-eight, Plummer, disc)
  - `analysis.go` — convergence-order estimator, reversibility test, Lyapunov estimate, diagnostics series
  - `report.go` — self-contained HTML (canvas animation + energy-error plot)
- `cmd/orrery` — CLI: `run`, `bench`, `order`, `elements`, `report`, `gen`
- tests + `demo.sh`

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Integrator suite (Euler, symplectic Euler, leapfrog, Yoshida-4, RK4, adaptive DOPRI5) with conserved-quantity diagnostics | **required** |
| 2 | Barnes–Hut octree force solver, validated against direct summation (error vs θ) | **required** |
| 3 | Scenario DSL + generators + exact Kepler oracle & orbital-element conversion | **required** |
| 4 | Self-contained HTML viewer/report (animated orbits, energy-drift plot, integrator comparison) | **required** |
| 5 | Empirical convergence-order measurement per integrator | stretch |
| 6 | Time-reversibility test + Lyapunov exponent estimate (shadow-particle) | stretch |
| 7 | Wisdom–Holman Kepler-drift splitting integrator for hierarchical systems | stretch |
| 8 | Individual/adaptive time-step close-encounter handling (DOPRI5 + step control) | stretch (covered by 1 if adaptive) |

## Gates
Kepler orbit matches analytic oracle; figure-eight returns to start after one period; energy error ordering
symplectic < non-symplectic over long runs; BH matches direct as θ→0; Plummer virial ratio ≈ 1.
