# Adversarial review

Written after phase 2, attacking the build as a hostile reviewer. Every item below was reproduced
first, then fixed; `review_check.sh` replays each probe and fails if any regresses.

| # | Finding (how it was hit) | Severity | Fix |
|---|---|---|---|
| 1 | **Crash**: a model with 100 000 nested parentheses overflowed the stack (SIGABRT). | high | Parser nesting limit (2000) with a positioned error; CLI worker thread has a 1 GiB stack for long left-nested chains. Test `absurd_nesting_is_an_error_not_a_crash`. |
| 2 | **Lazy shortcut**: integer ranges above 4096 values (`0..65535` counters, `mod 65536`) were rejected — "table-based encoding too large". A model checker that cannot do a 16-bit counter is not credible. | high | Added `bv.rs`: signed bit-vector circuits (add/sub/mul/neg/compare/div-mod by constants) and a bit-vector value form with union semantics; `domain()` is now an arithmetic comparator rather than a loop over codes. Range-overflow check kept (error unless `--lax`). `tests/bv.rs` checks every circuit exhaustively. |
| 3 | **Wrong answer risk**: `domain()` handed variable *ids* where BDD *nodes* were required (types coincide) → spurious "assignment can leave its type" errors on big ranges. Found by the first big-range run. | high | Convert ids to nodes; covered by the 16-bit counter example. |
| 4 | **Silent unsoundness**: with a reachable deadlock, `SPEC AG n < 3` PASSED although a reachable state had n = 3 (CTL only sees infinite paths). Only `INVARSPEC` caught it. | high | Loud deadlock warning explaining the semantics; new `--stutter` flag (deadlock states get a self-loop) implemented in both engines and fuzzed; philosophers example demonstrates the difference. |
| 5 | Division by zero silently deleted transitions (`n / m` with m = 0 produced a deadlock, no message). | medium | Compile error when the divisor can be zero in a legal state (guard it, or `--lax`). |
| 6 | Invalid UTF-8 input panicked (`unwrap`). | medium | Proper message, exit 2. Also: unreadable file, unknown flag, missing value all give exit 2 with a message. |
| 7 | **Product-model bug (found by fuzzing)**: `preimage` quantified a stale cube, so LTL tableau variables leaked into results (wrong LTL verdicts on 1 of ~90 random models). | high | `finish_extension` recomputes the cubes. 2 500 random models now agree. |
| 8 | **GC bug (found by `--gc-stress`)**: `eg_fair` kept `nz` unpinned across nested fixpoints; `ex`/`eu` computed `fair` before pinning their operands. | high | Pin discipline fixed; GC-stress runs on all examples and in the fuzzer. |
| 9 | Input variables leaked into the state-space BDD (`space` included input domains) → `sat_count` panic. | high | Inputs excluded from `space`. |
| 10 | Counterexample for a 65 536-step counter printed 65 536 states. | medium | Terminal traces abbreviate (head/tail, loop position noted); `--full-traces` opts out; HTML keeps head/tail columns. |
| 11 | Vacuous passes (no fair path from init) were indistinguishable from real passes. | medium | `(vacuous: …)` marker per spec, warning, and a banner in HTML. |
| 12 | "fair states" count looked like a reachable count; "1 states" grammar; duplicate `NAME`s accepted; an empty spec list exited 0 silently. | low | Relabelled ("N of M legal states start an infinite fair path"), pluralisation, duplicate names are an error, no-spec warning. |
| 13 | Expression printer parenthesised everything (`((a & b) & c)`), making reports unreadable. | low | Precedence-aware printer; round-trip tests. |
| 14 | `EF x = 3` parsed as `(EF x) = 3` and failed with a baffling type error. | medium | Temporal prefix operators take a comparison-level operand, so `AG x = 3` means `AG (x = 3)` while `AG p -> q` is still `(AG p) -> q`. |
| 15 | Elevator example (my own model) failed `floor0_served` — a *real* starvation bug in my controller (re-pressing the current floor's button). | n/a | Kept as `elevator_naive.smv` (a showcase lasso) and fixed in `elevator.smv`. |

## Fresh run-through
`./review_check.sh` re-runs every probe above (hostile inputs, long traces, big ranges, deadlock
semantics, gc-stress equality across all examples, LTL/CTL agreement) and ends `REVIEW CHECK PASSED`.
