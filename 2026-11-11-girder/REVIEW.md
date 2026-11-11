# Girder — adversarial review (Phase 3)

Method: attacked the CLI/parser with hostile model files, probed solver scaling, mutated physical
setups (mechanisms, orphans, ill-scaled members), and inspected rendered reports (light, dark, phone).
Every finding below was reproduced, fixed, and (where possible) pinned with a regression test.

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **High** | Skyline Cholesky judged pivots against the *global* max diagonal, so valid but badly scaled frames (axially stiff, very slender members: I=1e-9) were rejected as "mechanisms" | Pivot test now relative to each row's own diagonal; `TestIllScaledFrameIsNotAMechanism` |
| 2 | **High** | A 600×600 mesh with the direct solver would try to allocate ~7 GB and die | Factor-storage guard (`ErrTooLarge`, advises `cg-ic0`); mesh cap lowered 400k → 250k cells |
| 3 | Med | Singular systems gave "pivot 5 = -2e-16" — no hint where | Failing row mapped back (through RCM and Dirichlet elimination) to node/coordinates/dof: "node 2 (x=1,y=0) can move freely in y" |
| 4 | Med | Frame node attached to no member produced the cryptic pivot error | Explicit "node N is not connected to any member" |
| 5 | Med | `bar … w=` / `i=` silently accepted and produced garbage moments for a pin-ended bar | Rejected with explanation |
| 6 | Med | A second `material` line after `mesh` was silently ignored (model solved with the old material) | Parse error |
| 7 | Low | `title a=1 a=2` failed as duplicate key (title is free text) | `title` handled before key=value parsing |
| 8 | Low | Model with no loads printed zeros with no explanation | CLI warns "no loads or prescribed displacements" |
| 9 | Low | Frame plot drew a support marker at only one (random) node | Marker at every supported node |
| 10 | Low | Reports were 3–11 MB (one `<polygon>` per sub-triangle) | Triangles bucketed into 64 colour levels, one `<path>` each: 3.4→1.2 MB, 10.9→3.8 MB |
| 11 | Low | Truss reports showed columns of zero shear/moment and 1e-14 reaction noise | Beam-only columns hidden; round-off reactions zeroed |
| 12 | Low | Unit-less `fixOrientation` was convoluted (map literal in a loop) | Rewritten |
| 13 | Info | Boundary nodal stresses converge only O(h) (Lamé bore σθ: 88.0→86.0→84.8 vs 83.3) — inherent to extrapolation | Tests assert displacements at tight tolerance and *centroid* stresses (O(h²)); documented in README |

Not a bug but recorded: Q4 under plane strain with ν→0.5 locks (standard); the validation suite uses ν=0.3.
Fresh run-through: all hostile inputs above now yield a precise error or correct answer; `go test ./...` green.
