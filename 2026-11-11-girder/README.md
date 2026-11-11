# Girder — finite-element structural-mechanics lab (Go)

**Status: Phase 4 (stretch + polish) complete.** All 4 required and all 4 stretch features work; the
adversarial review ([REVIEW.md](REVIEW.md), 13 findings, all fixed) is done. The verify script and final
README follow in phases 5–6. See [PLAN.md](PLAN.md).

## Quick start
```
go run ./cmd/girder validate -o validation.html      # closed-form verification suite
go run ./cmd/girder solve testdata/plate_hole.fem -o plate.html
go run ./cmd/girder solve testdata/portal.fem -o portal.html
go test ./...
```

## Built so far (required features)
1. **Elements + assembly + BCs** — tri3, tri6, quad4 plane stress/strain; 2-D beam-column and truss
   elements; point, traction, pressure and body loads; Dirichlet BCs (incl. prescribed values).
2. **Solvers** — CSR assembly, reverse Cuthill–McKee, skyline Cholesky, Jacobi- and IC(0)-PCG.
3. **Verification vs. closed-form physics** — Kirsch SCF≈3.03, Lamé cylinder, Timoshenko cantilever,
   beam theory for frames, patch test to 1e-10, convergence orders (tri3/quad4 → 2, tri6 → 3).
4. **Post-processing + report** — Gauss-point stress, nodal recovery, von Mises, force-balance check,
   SVG contour plots on the deformed shape, self-contained HTML reports, text model-file CLI.

## Stretch features (phase 4)
5. **SIMP topology optimisation** — `girder topopt -case mbb -o topo.html` (mbb / cantilever / bridge),
   density filter, OC update, evolution gallery and convergence chart.
6. **Modal analysis** — `girder modal testdata/modal_plate.fem` (consistent mass, shift-invert subspace
   iteration); frames match Euler–Bernoulli frequencies to <0.2 %.
7. **tri6 quadratic triangles** — observed displacement convergence order ≈ 3.2 vs 2 for tri3/quad4.
8. **Heat conduction** — `girder heat testdata/heat_hole.fem` on the same element machinery.

## Phase 3 review
See [REVIEW.md](REVIEW.md).
