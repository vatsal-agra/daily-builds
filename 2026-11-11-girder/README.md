# Girder — a finite-element structural-mechanics lab (Go, stdlib only)

Describe a part — cantilever, plate with a hole, thick cylinder, bridge truss, portal frame — apply loads
and supports, and Girder meshes it, assembles the stiffness matrix, solves it with its own sparse
linear algebra, recovers stresses and draws von-Mises contours on the deformed shape. It can then
*design* the part (SIMP topology optimisation), find its vibration modes, or solve heat conduction.
Everything — elements, RCM reordering, skyline Cholesky, IC(0)-PCG, eigensolver, renderer — is written
from scratch with no dependencies.

## Run it
```bash
./verify.sh                                              # everything: lint, tests, CLI, hostile inputs → ALL GREEN
go run ./cmd/girder validate -o validation.html          # closed-form verification report
go run ./cmd/girder solve testdata/plate_hole.fem -o plate.html     # stress contours (open in a browser)
go run ./cmd/girder solve testdata/portal.fem -o portal.html        # frame: moment diagram + deflected shape
go run ./cmd/girder topopt -case mbb -o topo.html        # grow an MBB beam (~20 s); cases: mbb|cantilever|bridge
go run ./cmd/girder modal testdata/modal_plate.fem -o modes.html    # natural frequencies + mode shapes
go run ./cmd/girder heat testdata/heat_hole.fem -o heat.html        # temperature field
go run ./cmd/girder mesh testdata/dam.fem                # mesh statistics
```
Needs Go ≥ 1.24 only (Node/Playwright were used just to eyeball the HTML while developing).

### Model file format
```
title Plate with a circular hole
material E=200000 nu=0.3 t=1 [plane=strain] [rho=7850] [k=45]
mesh rect w=100 h=10 nx=60 ny=6 type=quad4        # also: annulus a= b= nr= nt= ; quarterhole a= L= nr= nt=
fix where x==0 dofs=xy                             # selections: x|y|r with < <= == >= > joined by &&
traction where y==10 tx=0 ty=100                   # also: pressure, load, body, temp, flux, source
solve solver=cg-ic0                                # direct | cg-jacobi | cg-ic0
plot fields=vonmises,syy,disp mesh=on
```
Frames: `frame`, `node X Y`, `beam N1 N2 E= A= I= [w=] [rho=]`, `bar N1 N2 E= A=`, `support N dofs=xyr`, `force N fx= fy= mz=`.
See `testdata/` for six structural, two modal and one thermal example.

## Features
**Required**
1. **Elements, assembly, BCs** — tri3 (CST), tri6, quad4, plane stress/strain; Euler–Bernoulli beam-column and truss
   elements; point, traction (constant or position-dependent), pressure and body loads; prescribed displacements.
2. **Linear solvers** — CSR assembly, reverse Cuthill–McKee, skyline Cholesky (with memory guard and "node N can
   move freely in y" mechanism diagnostics), Jacobi- and incomplete-Cholesky-preconditioned CG.
3. **Verification vs. closed-form physics** — Kirsch SCF (3.03), Lamé thick cylinder, Timoshenko cantilever,
   beam theory for frames, patch test to 1e-10, K·(rigid body) = 0, measured convergence orders (tri3 1.96, quad4 1.99, tri6 3.2).
4. **Post-processing + reports** — stress recovery (Gauss-point extrapolation for quad4), von Mises/principal stresses,
   force-balance and energy checks, SVG contours on the deformed shape, moment/axial diagrams, self-contained
   light/dark/phone-friendly HTML reports.

**Stretch (all shipped)**
5. **SIMP topology optimisation** with density filter and optimality-criteria update, three load cases, evolution gallery.
6. **Modal analysis** — consistent mass, shift-invert subspace iteration with Rayleigh–Ritz; cantilever/pinned beam
   frequencies match theory to <0.2 %, plate fundamental within 1 % of beam theory.
7. **Quadratic triangles (tri6)** with the convergence-order study.
8. **Steady heat conduction** on the same isoparametric machinery (slab, radial annulus, source+flux bar checked exactly).

## Why this, today
The ledger is full of logic, symbolic maths, codecs and compilers, but nothing that discretises a *PDE*. FEM is
satisfying because physics gives a ground truth: it is only "right" if it reproduces a stress concentration
factor of 3, textbook beam deflections and the right convergence slope. The adversarial review
([REVIEW.md](REVIEW.md)) found a real numerical bug that way (a pivot threshold that rejected valid, badly scaled
frames) plus hostile-input and scaling problems; all 13 findings are fixed and pinned by tests.

## Known limits
Linear elasticity, small strain only; boundary-node stresses converge O(h) (displacements and centroid stresses are
much better); quad4 locks near ν = 0.5 (plane strain); no free-free modal analysis; the direct solver is capped by a
memory guard (use `cg-ic0` for very large meshes).

## Where a human could take this next
Adaptive h-refinement from a Zienkiewicz–Zhu error estimator; mixed/B-bar elements for incompressibility; contact
and plasticity (Newton–Raphson load stepping); 3-D tet/hex elements and sparse multifrontal or AMG solvers;
buckling and transient (Newmark) dynamics; STEP/Gmsh import; an interactive WebAssembly front-end; a stress-constrained
or manufacturable topology optimiser.

Layout: `fem/` library (≈6 k lines incl. tests), `cmd/girder/` CLI, `testdata/` models, `PLAN.md`, `REVIEW.md`, `verify.sh`.
