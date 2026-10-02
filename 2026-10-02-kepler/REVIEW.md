# Adversarial review (Phase 3)

I attacked the Phase 2 build as a hostile reviewer: odd CSVs, degenerate targets, huge/tiny
magnitudes, noisy data, determinism, race detector, CLI misuse, rendered the HTML report and looked at it.
Every finding below was **reproduced first, then fixed, then re-run**.

| # | Finding (how I hit it) | Severity | Fix |
|---|------------------------|----------|-----|
| 1 | **Unclean winners**: kinetic-energy run returned `0.5 * v * m^1 * v`. Snapped (`m^1`→`m`) copy had error 1e-14 vs raw 3e-15 and was dropped from the front as "not strictly better" — float noise decided the winner. | High (core output quality) | Errors < 1e-12 are treated as equal (`floor`); cleaned variant inserted first so it wins ties. |
| 2 | **Vestigial constants**: pendulum returned `(L/(0.0253*g) + 4.59e-07)^0.5`. Fit leaves tiny junk terms. | High | New `Prune` pass: replace a subtree by a child / 0 / 1 when error stays within 2 % (+float floor), refit, repeat. |
| 3 | **Overfit model selection**: 1 %-noise decay law picked a complexity-31 formula with `cos(69.7/(t-t^3.11))` because its holdout error was luckily 2× lower than the true law (winner's curse on 30 holdout rows). | High | Selection now minimises `err·exp(0.06·complexity)` (error floored at 1e-12): an extra node must buy ~6 % error. Picks `99.97*0.7407^t` (cplx 8). |
| 4 | **No like-term collection**: `x^3 - x - x` selected for a noisy cubic; `x*x*c` printed unsimplified. | Medium | `collectTerms` (sum flattening with coefficient merging) + `(c*a)*a → c*a²` rules in the simplifier. |
| 5 | **Cluttered Pareto front**: 47-node entries that improved error by 0.3 % polluted the table and chart. | Medium | A model must cut training error ≥1 % to stay on the front. |
| 6 | **Ugly printing**: `a + -2*b`, `v - -110.7`, `2^(-1)`. | Low | Printer flips `+ -x` / `- -x` forms; simplifier rewrites `a - (-c)`. |
| 7 | **No time budget / Ctrl-C**: a long run could not be bounded or aborted without losing everything. | Medium | `-time` budget; SIGINT/SIGTERM end the search gracefully and print the front found so far. |
| 8 | **CLI flags after positional args silently misparsed**: `kepler gen kinetic -n 40` errored with a misleading message (Go `flag` stops at first positional). | Medium | Interspersed flag parser. |
| 9 | **CSV robustness**: Excel UTF-8 BOM corrupted the first header; CRLF untested. | Medium | BOM stripped; CRLF verified. Ragged rows, non-numeric/NaN/Inf cells, <5 rows, invalid identifiers, unknown `-target` all give line-numbered errors (checked). |
| 10 | **Silent no-holdout on small data** (<20 rows). | Low | CLI prints a note that selection used training error. |
| 11 | **Python-style `x**2`** rejected by parser. | Low | `**` accepted as `^`. |
| 12 | **Report**: leftover dead code in Pareto axis maths; "rediscovered" tag unstyled (not green). | Low | Cleaned axis computation; tag CSS fixed. |

## Checked and found OK
- Determinism: same seed ⇒ byte-identical front (islands synchronise per generation).
- `go test -race` clean; invalid candidates (NaN/Inf, division by zero, log of negative) never enter the population.
- Scale: targets of 3e6·x² and 2e-7·x^1.5 recovered (constants fit by NM + significant-digit snapping); 5,000-row dataset solved in ~1 s via row subsampling.
- Constant target and duplicate-x data return the trivial constant model instead of crashing.

## Known limitations (documented, not hidden)
- Search is stochastic; hard laws (many variables, deep nesting) may need `-gens/-pop` raised or several seeds.
- `exp(4.60 - 0.3t)` style answers are equivalent to `100*exp(-0.3t)` but the engine cannot know `4.60431 = ln 100`; it reports what it found.
- No unit/dimension analysis (would be a good stretch for a human).
