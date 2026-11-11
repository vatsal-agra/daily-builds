# Girder — finite-element structural-mechanics lab (Go)

**Status: Phase 2 (core build) complete.** Required features 1–4 work end to end; stretch features,
adversarial review, polish and the full verify script follow in later phases. See [PLAN.md](PLAN.md).

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
