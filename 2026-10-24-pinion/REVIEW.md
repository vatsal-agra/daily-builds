# Adversarial review

Method: I attacked the code as a hostile reviewer — a parsing battery for versions and
constraints, a property test of the set algebra against pointwise membership (3,000 random
pairs × every sample version), hostile CLI/manifest/lockfile inputs, performance probes
(1,500-package chain, 40×25 wide graph, 12,000-deep failure proof), reading the generated
explanations for quality, and the differential fuzzer (≈1,900 registries in several shapes,
against a brute-force oracle with every learned clause re-proven). Findings are listed in the
order found; every one is fixed and pinned by a test in `test/review_regression_test.rb`.

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| F1 | **crash** | `Constraint.parse("||")` returned `nil` (Ruby's `"||".split("||")` is `[]`), so a manifest with `"dep": "||"` died later with `NoMethodError`; `"^1 ||"` was silently accepted as `^1`. | split with limit `-1`; any empty alternative is a `ParseError`. |
| F2 | UX | `"~>"` / `">="` alone reported `invalid version ">"`; `"1.2.3 - "` reported `invalid version "-"`. | Dedicated messages: *operator "~>" needs a version*, *dangling '-' in range*. |
| F3 | wrong output | Internal "before any prerelease" bound leaked into display: `!=1.2` printed `>=1.3.0-0`. | Display folds `X.Y.Z-0` lower bounds to `X.Y.Z`. |
| F4 | **wrong output** | Range `[0.0.0, 0.1.0)` printed as `^0.0.0`, which *means* `<0.0.1` — the explanation would have misstated a constraint. | Caret form is only used where it round-trips (`0.minor>0`, `major>0`). Round-trip property test added. |
| F5 | policy bug | With prereleases opted in, `newest` picked `2.0.0-rc.1` over stable `1.9.0` (higher precedence). | Candidate pool prefers stable releases; falls back to prereleases only if nothing else matches. |
| F6 | **crash** | Reporter was recursive: a failure proof 12,000 steps deep raised `SystemStackError`. | Reporter walks the proof with an explicit task stack; output is byte-identical to the recursive version on 600 random proofs, 12k-deep proof now renders (24k lines). |
| F7 | **hang** (found by fuzzer, seed 53) | A package depending on *itself* made the "would this decision conflict immediately?" check always true, so the solver re-chose the same package forever (`decisions=1`, infinite loop). | Conflict check evaluates the tentative version against the package's own terms instead of treating them as satisfied. |
| F8 | robustness | Any unexpected exception printed a Ruby backtrace and exited 1 (indistinguishable from "unsolvable"). | `bin/pinion` maps internal errors to a one-line message + exit 70; `EPIPE`→0, `Interrupt`→130; `PINION_DEBUG=1` shows the trace. |
| F9 | UX | `pinion why zzz` said only "not part of the solution". | Says whether the package exists in the registry. |
| F10 | test bug | Fuzzer's "explanation ends in failure" check failed on line-wrapped text ("version solving\n  failed"). | Compare on whitespace-normalised text. |
| F11 | **correctness of proofs** (found by fuzzer) | `DependencyCause` leaves for self-dependencies collapsed to a single term, so the reporter and proof checker had no depender/dependency to show. | The cause now carries `(package, range, dep, dep_set)` explicitly; reporter and proof checker read from it. |
| F12 | gap | A locked version that was later yanked passed `verify` silently. | `verify` still succeeds (the lock is consistent) but prints a `warning:` per yanked pin, and `--json` has a `warnings` array. |

## Re-run
After the fixes: the parsing battery, set-algebra property test, hostile CLI session,
performance probes and 1,300 fresh fuzz registries (8-10 packages, up to 8 versions,
densities 0.2-0.5) all run clean — zero disagreements with the oracle, 6,000+ learned
clauses entailed.

## Known limitations (documented, not bugs)
* Display folds `-0` bounds, so `<2.0.0` printed for an internal `<2.0.0-0` is exact for
  releases but would admit `2.0.0-beta` if re-parsed; prerelease handling is by policy
  (hidden unless opted in) so this never changes a resolution.
* Backjumping rebuilds the trail (O(trail)), so pathological 10k+-package chains take
  tens of seconds; typical graphs resolve in milliseconds.
* The empty constraint `""` means "any version" (kept, matches Bundler/npm).
* No network access: registries are JSON files; there is no download/install step.
