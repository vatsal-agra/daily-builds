# Girder — Plan

## Concept
Girder is a from-scratch **finite-element structural-mechanics laboratory** in Go (stdlib only).
Describe a part — a cantilever, a plate with a hole, a bridge truss, a portal frame — apply loads and
supports, and Girder meshes it, assembles the stiffness matrix, solves it with its own sparse linear
algebra, recovers stresses, and draws von-Mises contours on the deformed shape. It then goes one step
further and *designs* the part: SIMP topology optimisation grows an MBB beam out of a solid block.

It is the repo's first continuum-mechanics / PDE-discretisation build. Everything prior is
logical, symbolic, signal-processing or discrete; this one turns a partial differential equation
(elasticity) into a sparse symmetric positive-definite linear system.

## Why it's interesting
* FEM is checkable against closed-form physics. Girder is only "done" when it reproduces
  **Kirsch's stress-concentration factor of 3.0** at a hole, **Timoshenko's cantilever deflection**,
  the **Lamé thick-cylinder** stresses, beam-theory natural frequencies, and the textbook
  **convergence rates** (CST ~ h², T6 ~ h³ in displacement) — and the patch test passes to round-off.
* Real numerical engineering: reverse Cuthill–McKee reordering, skyline/banded Cholesky, incomplete-Cholesky
  PCG, nodal stress recovery, generalized eigenproblems, optimality-criteria updates, density filters.
* Visual and satisfying: the optimiser's output looks like a bone / bridge.

## Architecture
```
fem/
  linalg.go    dense helpers, small LU/Cholesky, symmetric eigen (Jacobi)
  sparse.go    triplet→CSR, matvec, RCM ordering, skyline Cholesky, Jacobi/IC(0) PCG
  elements.go  isoparametric 2-D elements (tri3, tri6, quad4) + Gauss rules, B matrices
  frame.go     2-D Euler–Bernoulli beam-column and truss elements
  mesh.go      generators: rectangle (tri/quad), quarter-plate-with-hole, annulus sector, refine
  model.go     Model: materials, BCs, loads, assembly, solve (elimination), reactions
  post.go      stress/strain at Gauss points, nodal recovery, von Mises, energy, error norms
  thermal.go   steady-state heat conduction on the same element machinery
  modal.go     lumped/consistent mass, generalized eigensolver (shift-invert subspace iteration)
  topopt.go    SIMP compliance minimisation, density filter, OC update (quad4 grid)
  render.go    SVG contour/mesh/deformed renderer, self-contained HTML report
  parse.go     text model-file format → Model
cmd/girder/    CLI: solve | validate | topopt | modal | report | mesh
testdata/      example model files
```

## Feature list
| # | Feature | Tier |
|---|---------|------|
| 1 | **Elements + assembly + BCs**: tri3 (CST), quad4, 2-D frame/truss elements; plane stress/strain; point, edge-traction, pressure and body loads; Dirichlet BCs | **required** |
| 2 | **Linear solvers**: CSR assembly, RCM reordering, skyline Cholesky (direct), Jacobi- and IC(0)-preconditioned CG (iterative), cross-checked against each other | **required** |
| 3 | **Verification suite vs. closed-form physics**: patch test, cantilever (Timoshenko), Kirsch plate-with-hole SCF≈3, Lamé cylinder, convergence-rate measurement | **required** |
| 4 | **Post-processing + report**: Gauss-point stress, nodal recovery, von Mises, reactions/equilibrium check, SVG deformed-shape contour plots, self-contained HTML report, text model-file CLI | **required** |
| 5 | **SIMP topology optimisation** (MBB beam / cantilever / bridge), density filter, OC update, animated-free SVG gallery | stretch |
| 6 | **Modal analysis**: consistent/lumped mass, generalized eigenproblem; frames vs. Euler–Bernoulli frequencies, plates vs. beam theory | stretch |
| 7 | **tri6 quadratic triangles** with convergence-order study (h³) | stretch |
| 8 | **Steady heat conduction** (same isoparametric machinery) vs. analytic 1-D & annulus solutions | stretch |

Targets: all 4 required + at least 4 stretch; `verify.sh` runs everything and ends ALL GREEN.
