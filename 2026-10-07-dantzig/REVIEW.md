# REVIEW — adversarial pass over Dantzig

Method: after the core build, I attacked it as a hostile reviewer, with three kinds of attack.

1. **Hostile inputs.** Empty and degenerate models, absurd magnitudes, endless integer domains, cycling LPs (Beale, Kuhn, Klee–Minty), a mutation fuzzer for the parser, and the CLI's error paths.
2. **An independent oracle.** `tools/crosscheck.py` compares Dantzig with HiGHS (`scipy.optimize.milp`) on about 2,000 generated, random and "wild" models. The wild ones have free and negative bounds, ranges, equalities, unbounded and infeasible cases.
3. **Attacks on the checker.** The proof checker has to reject tampered proofs, so I tampered with proofs on purpose.

Every finding below was real and reproduced before it was fixed. Each fix has a regression test, listed in the last column.

| # | Sev | Finding (how I found it) | Fix | Regression |
|---|-----|--------------------------|-----|------------|
| 1 | **critical** | **Dual simplex never terminates on dual-degenerate problems.** The root LP of the "hard" sudoku (zero objective, so every reduced cost is 0 and every ratio-test row ties) ran for more than 2 minutes with no end. | Stall detection in the dual, then a cost perturbation (≈1e-6, sign-preserving, nonbasic columns only). The perturbed dual runs to primal feasibility, the true costs are restored, and a primal clean-up pass finishes. Cutoffs are disabled while the costs are perturbed, because the objective is no longer a valid bound. | `TestDegenerateBinaryDataPrimalVsDual` (6000 0/1-data LPs, primal-only vs default path), `TestCyclingExamples`, `TestKleeMinty`, `TestDegenerateAssignmentLPs`; sudoku is now in the demo |
| 2 | **high** | **The simplex iteration cap was cumulative across the whole branch & bound run.** After about 50k total pivots every later node LP "failed", so leaves became uncertified. I saw this on a model with an endless integer domain, where the status flipped to UNKNOWN with the note "LP solver failed". | The budget is now per `Solve` call (`iterBase`). | `TestRegressionEndlessSearchLeavesReadableProof` |
| 3 | **high** | **`--time` was ignored inside an LP or the diving heuristic.** The hard sudoku with `--time 1` ran about 3.9 s. | A deadline inside the simplex loops. A node that times out becomes an `open` leaf. Certification of open nodes stops being attempted once the budget is well past. | `TestRegressionTimeLimitBindsOnHardSudoku` |
| 4 | **high** | **Deep proof trees were unreadable.** A search of 100k+ nodes wrote nested JSON that Go's decoder rejects ("exceeded max depth"), and the recursive checker could blow the stack. | Proofs are a flat `nodes` array with child indices, a forward-only DAG check (a tree, no repeated or unreachable nodes), and an iterative checker. | `TestRegressionEndlessSearchLeavesReadableProof`, `TestProofTamperingIsRejected` |
| 5 | **medium** | **A model with zero variables produced a proof the checker rejected.** The empty solution list was dropped by `omitempty`, so "optimal without a solution". | `x` is serialised as `null` or `[]` explicitly. | `TestRegressionZeroVariableModel` |
| 6 | **medium** | **Float-range hazards.** `1e400` silently became +Inf in the float model. `1e-21 x >= 1` could not be pivoted on and returned UNKNOWN with no explanation. | `Validate` rejects \|value\| > 1e12 and nonzero matrix or objective coefficients below 1e-6, with a "rescale your model" message. The exact checker is never involved with garbage. | `TestRegressionNumericRange` |
| 7 | **medium** | **An unbounded LP relaxation of a MIP was reported only as `unbounded_relaxation`.** The cross-check against HiGHS caught this. It happened in 6 of about 1,850 wild models, where HiGHS says infeasible or unbounded. | A zero-objective feasibility MIP now classifies it: a certified integer point plus an integral ray gives **UNBOUNDED**, and a Farkas/gcd tree gives **INFEASIBLE**. The checker verifies the MIP-unbounded certificate (an integral base point, a ray that is integral on integer variables). | `TestInfeasibleAndUnboundedMIP` (incl. fractional-ray tamper) and the cross-check |
| 8 | **medium** | **My own fix for #7 could hang.** On an endless integer domain the feasibility search never ended; the test process ate memory and was killed after 160 s. | The classification search is node-capped and first tries boxes `[-10,10]` and `[-1000,1000]` on integer variables. A point in a sub-box is feasible for the original model. | same test, now sub-second |
| 9 | **medium** | **Parity infeasibility is unprovable by B&B on free integers.** `3x - 3y = 1` has an LP-feasible line and no integer point. | New `gcd` leaf: the checker re-derives "no multiple of the coefficient gcd lies in the row's range" exactly, with no box needed. Found at the root before any LP runs. | `TestGCDRows`, `parity.lp` in the CLI test |
| 10 | **low** | **`Format` dropped zero-cost variables from the objective.** The mutation fuzzer showed that re-parsing then reordered the variables. Proofs index variables, so order is part of the model's meaning. | The writer lists exactly the zero-cost variables needed for a faithful re-parse, or all of them if a cheap choice would not reproduce the order. Long expressions wrap with the operator at line end. | `TestParserMutationFuzz` (30k mutations: no panic, stable round trip), `TestFmtIsStableForEveryGenerator` |
| 11 | **low** | **Refactorisation dominated the runtime of large models.** The T = B⁻¹M product was a dense triple loop (hard sudoku 5.9 s). | The product iterates the sparse rows of A (2.6 s). | existing correctness tests |
| 12 | **low** | **CLI paper cuts.** The flag library's usage dump, `--proof` combined with `--no-proof` silently ignored, `--values` unvalidated, a duplicated note line, giant exact fractions printed in full, and a compiled test binary committed in phase 2. | All fixed, plus a `.gitignore`. | `TestRegressionFlagErrors` |

## Things I attacked that held up

- **The checker.** Proofs with a worse incumbent, an infeasible incumbent, a wrong objective, perturbed multipliers, a swapped-out subtree, a different model (hash), a fractional MIP ray, and a Farkas vector that needs an infinite bound are all rejected.
- **Cycling LPs.** Beale and Kuhn solve and certify. Klee–Minty n = 2..14 solves and certifies, and the optimum is exactly 5ⁿ.
- **Primal vs dual paths.** On the 6000 degenerate 0/1 LPs the two paths agree on status and objective, and every result is certified.
- **HiGHS cross-check.** The latest run covers about 2,000 models of every family with 0 mismatches. HiGHS answers 945.999999 on a big-M model where Dantzig returns the exact 946.

## Known limitations (not defects, listed for honesty)

- Dense tableau: memory is O(m·(n+m)) and each pivot is O(m·(n+m)). Practical up to a few hundred rows.
- No scaling and no presolve. Data must stay within [1e-6, 1e12] in magnitude.
- A MIP over unbounded integer variables can have an endless B&B tree. Use `--time`; the partial proof stays verifiable.
- Exact certification of each leaf costs one rational solve of the basis, which is O(m³) in rational arithmetic. `--no-proof` skips it.
- Branching is single-variable. There are no cutting planes and no restarts.
- Dive, bounds and pruning use float tolerances. Exactness is enforced at the certificate, never assumed. A float mistake shows up as an `uncertified` leaf, not as a wrong answer.

## Fresh run-through (gate)

After the fixes I re-ran everything from scratch:

1. `go test ./...` passes.
2. `crosscheck.py` against HiGHS shows 0 mismatches.
3. The CLI regression suite (`cmd/dantzig/cli_test.go`) reproduces each of findings 1–12 and none recurs.
