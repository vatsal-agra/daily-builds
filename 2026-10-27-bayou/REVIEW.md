# REVIEW — adversarial pass over the Phase-2 build

Method: I read the code as a hostile reviewer, then attacked it — hand-written nasty inputs
(`/tmp` probe files: BOM, CRLF, tabs, empty file, cycles, 300-variable dense nets), random
differential tests against an independent enumeration oracle, mutation testing of the core
(deliberately breaking 10 lines and checking the tests notice), and timing runs on large
networks. Every finding below was **fixed**, and each has a regression test (file in brackets).

## Findings

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | **critical** | **Silent data corruption in the CSV reader.** `none`, `NA`, `null` were always treated as "missing", so a legitimate state called `none` (the umbrella example!) was dropped. Found because EM's log-likelihood on real data exceeded what the true model can achieve (−691 vs ≥ −12 779) — an impossible number. | A real state name always wins; the marker is only consulted if no state matches. `WriteCSV` picks a missing marker (`?`, `NA`, …) that no state uses so files round-trip. [`TestCSVStateNamedLikeMissingMarker`] |
| 2 | **critical** | **Process killed / panic on high-treewidth networks.** `marginals` on a random 300-variable net panicked with `makeslice: len out of range`; `query` ran 88 s, swapped, and was OOM-killed. | Typed `factor.TooLargeError`; the elimination planner and the junction-tree builder compute the biggest table (log₂) *before allocating* and fail with `ErrTooLarge` ("treewidth too large… try `bayou approx`") in 0.6 s. `info` now reports treewidth and warns. [`TestIntractableNetworksFailGracefully`, `TestInfoWarnsWhenIntractable`] |
| 3 | high | **VE ordering was O(n³)**: querying a 1,500-variable chain took 11 s (the intractable case took 3.3 s just to fail). | Replaced with a cached, incremental min-fill planner (re-scores only the neighbours of an eliminated vertex); 11 s → 0.1 s. Junction-tree construction no longer builds all O(k²) clique pairs or compares every clique pair (5,000-variable net: 13 s → 0.75 s). [`TestLongChainPosteriorMatchesClosedForm`] |
| 4 | high | **A quoted `"*"` state was treated as the wildcard**, silently filling every parent row. | Wildcard only for bare `*` tokens. [`TestQuotedStarIsAStateNotAWildcard`] |
| 5 | high | **Writer/lexer escape mismatch**: `strconv.Quote` escapes (`é`, `\t`) were not understood by the lexer, so `FormatBN` → `ParseBN` could change names. | Own quoting routine matched to the lexer's escapes; control characters in names/states are rejected up front by `AddVar`. [`TestAwkwardNamesRoundTrip`] |
| 6 | medium | UTF-8 BOM (Excel/Notepad) made both `.bn` and CSV files unreadable ("unknown declaration"). | BOM stripped in lexer and CSV reader. [`TestParserAcceptsBOMCRLFSpacesFractions`, `TestCSVErrors`] |
| 7 | medium | `cpt X = 0.5 0.5` (space separated, the natural thing to type) was rejected with a confusing message. | Commas optional; trailing comma continues onto the next line; fractions (`1/3`) accepted. |
| 8 | medium | An empty file "validated OK" as a 0-variable network. | Error: "the network declares no variables". |
| 9 | medium | Rows summing to 1±1e-6 passed validation but were used un-normalised, so `P(evidence)` was off by up to 1e-6 relative. | Parsers renormalise rows that deviate by more than 1e-12 (rows already exact stay bit-identical, so round-trips are exact). [`TestRowsAreRenormalizedButExactRowsUntouched`] |
| 10 | medium | `learn --truth` on a latent-variable model printed "KL = 19.9": meaningless, since a hidden variable is only identifiable up to relabelling its states. | With latent variables the report compares data log-likelihood under truth vs learned instead. |
| 11 | low | Tiny posteriors printed as `0.000000` (a 1e-9 probability looked impossible). | Scientific notation below 1e-4. |
| 12 | low | Wording: "given {nothing}", "variable X (needed by the family of X) is latent". | Reworded; latent-column error now points at `--em`. |
| 13 | low | Code smells: package-level mutable state in the row filler (`explicitSeen`, `dupRow`) — not re-entrant; dead stub `project()` in `factor`; `_ = sort.Ints` placeholders; dead variables in the BIF `default` branch (which also mis-ordered `default` vs explicit rows). | Removed / made local; BIF `default` now fills exactly the rows no explicit entry set, in any order. |

## What the mutation run showed about the *tests*

Ten deliberate bugs were injected; 3 real survivors exposed missing tests, now added:
EM never stopping on convergence (`TestEMStopsWhenConverged`), barren-node pruning disabled
(`TestBarrenNodePruning` via `Result.Eliminated`), and MAP/argmax tie-breaking
(`TestMAPTieBreaksToLowestState`). The other two "survivors" were equivalent mutants (a check
that is identical for the values it can see).

## Things I checked and found correct
* Enumeration vs variable elimination vs junction tree: 400 random networks (with exact-zero CPT entries, impossible evidence, disconnected graphs) agree to 1e-9 on posteriors, joint posteriors, family marginals and log P(e).
* MAP/MPE: 300 random problems — the returned assignment achieves the brute-force optimum.
* d-separation: 120 random (X, Y, Z) triples — separated ⇒ numerically independent (dev < 1e-9); connected ⇒ numerically dependent for generic parameters.
* Underflow: a 400-variable chain with P(evidence) ≈ 10⁻⁸⁰⁰ gives the exact log-probability.
* Parsers never panic on 8,000 randomly corrupted inputs.

## Known limits (not bugs — documented in README)
* Exact inference is capped at 2²⁵ states per table; beyond that use sampling (`approx`, Phase 4).
* `Random` init of EM also randomises deterministic CPTs; use the default start for models with hard logic.
* BIF `table` for a child *with* parents uses Bayou's layout (parents slowest, child fastest); per-row entries are unambiguous and are what Bayou writes.
