# REVIEW — adversarial pass on Argus

I attacked the Phase-2 build as a hostile reviewer would: fuzzing the pieces that have an
independent oracle, feeding the CLI malformed and pathological models, and checking whether the
tool's own verdicts and counterexamples can be trusted. Every item below was **reproduced**, then
fixed; each has a regression test (file noted) so a fresh run-through hits none of them.

## Findings

| # | Sev | Finding | How it was found | Fix | Regression |
|---|-----|---------|------------------|-----|------------|
| 1 | **CRITICAL** | GPVW tableau dropped `true` from a node's `Old` set, so the acceptance set of `x U true`-shaped subformulas (e.g. `G false` negated) rejected nodes it must accept → the checker would say *"holds"* for properties that are violated. | Fuzzing the Büchi automaton against the direct lasso evaluator: `p U G false` on word `[6]` disagreed. | record `true` in `Old` | `tests/test_ltl.py::test_buchi_matches_direct_semantics` (400 random formulas × 12 words × 2 polarities) |
| 2 | HIGH | A transition that raised (OOB, assertion, range) caused the **whole source state to be skipped**, pruning its other successors. With `--all` the explored space was incomplete, and POR vs full search disagreed (an invariant violation was missed). | POR-vs-full fuzz over 250 random programs. | `successors(..., errors=[])` collects faulting statements and keeps the healthy ones; deadlock logic treats "only faulting statements" as *not* a deadlock | `test_por_matches_full_search_on_random_programs` |
| 3 | HIGH | The independent replay validator crashed with *"source state already errors"* on a legitimate trace whenever a *sibling* statement at some replayed state faulted. | same fuzz, validator running on every trace | validator uses the error-collecting successor function | same test |
| 4 | MED | An invariant that itself raises (`invariant bad: a[5] > 0`) was reported, but the validator rejected it → "INTERNAL ERROR: counterexample failed independent replay". | hand-written hostile model | validator re-evaluates the invariant on the final state and expects the same failure | `test_invariant_evaluation_error_is_replayable` |
| 5 | MED | An LTL atom that raises (`ltl l: <> (v[3]==1)`) produced a raw Python traceback. | hostile model | wrapped into an `ArgusError` that names the atom and shows the state | `test_atom_error_is_a_clean_error`, `test_review::test_05_06_*` |
| 6 | MED | `proc P(a, a)` was accepted; the second parameter silently shadowed the first. | hostile model | parse error "duplicate parameter name" | `test_errors` |
| 7 | LOW | Messages: `runtime error: runtime error: division by zero`; a violation in the initial state said "0 steps". | reading the output as a user | prefix de-duplicated; "violated in the initial state" | `test_review::test_07_*` |
| 8 | LOW | `--prop inv` printed the names of *all* invariants in the summary line, implying they had been checked. | reading the output | label lists only the invariants actually checked | `test_review::test_08_*` |
| 9 | LOW | An unbounded model ended with a bare "INCONCLUSIVE" and no advice. | `loop { x = x + 1; }` | hint: add a range (`var x: 0..7`) / bound loops / raise `--max-states` | `test_review::test_09_*` |
| 10 | LOW | Trace columns drifted when instance names were longer than 6 chars (`DataMedium0`). | abp trace | column width computed from the longest instance name | `test_review::test_10_*` |
| 11 | LOW | `graph` coloured *frontier* states (cut off by `--max`) as deadlocks. | `graph --max 6` | deadlock = red, finished = green, frontier = dashed | `test_review::test_11_*` |
| 12 | LOW | `sim --save` wrote a hacked JSON and `replay` of it crashed while rendering. | round-trip of a simulation | saved through the normal trace serialiser; replay skips rendering for simulations | `test_review::test_12_*` |
| 13 | LOW | The terminal-state self-loop in a liveness lasso always said "halted" even when the system was *deadlocked*. | `await x == 1` model with an `ltl` | wording distinguishes "all processes finished" from "DEADLOCKED" | `test_review::test_13_*` |
| 14 | INFO | **My own model comments were wrong.** I had claimed `peterson`, `prodcons` and `twophase` liveness fails without fairness. `verify` showed they hold anyway: every infinite run of those systems has all remaining processes moving, so no scheduler can starve one. | `argus verify models` | removed the false claims; added `fairness_ladder.arg`, a model where none/weak/strong give *three different verdicts* | `test_fairness_ladder_exact` |

## Things I attacked that held up
* **Soundness of "holds" for liveness**: 150 random cyclic programs × random LTL × {none, weak, strong}. An independent brute-force
  enumerator of short fair lassos (judged by the replay validator, not the SCC code) never found a violation the checker missed
  (`test_liveness_vs_bruteforce`, > 30 genuine violations exercised).
* **Fairness is monotone**: holds-without-fairness ⇒ holds-weakly ⇒ holds-strongly on every model (`test_fairness_is_monotone_on_models`).
* **Counterexamples are minimal for safety**: BFS level order, asserted on a 5-step case (`test_shortest_counterexample`).
* **The validator is not vacuous**: dropping a step, swapping steps, corrupting a state, and claiming a bogus deadlock are each rejected (`test_validator_rejects_tampered_traces`).
* **POR soundness**: same verdict set and violated-property names as full search on 250 random programs, with strictly fewer states overall.
* **Exact state counts** on hand-computable models, C-like operator precedence (`1 & 3 == 3` is `1 & (3==3)`), truncating division, guarded `either`, nondet, channels (`tests/test_lang.py`).
* **Hostile inputs** (unterminated block, duplicate labels, `await` inside `atomic`, `break` outside loop, wrong channel arity, unknown names, empty program, bad `-D`) all give a one-line error with source line and caret and exit code 2 — never a traceback.

## Known limitations (documented, not bugs)
* `X`, `U`, `R`, `W`, `F`, `G` are operators inside `ltl` formulas, so model variables with those exact names can't appear in LTL atoms (use longer names).
* Integers are unbounded unless given a `lo..hi` range; unbounded counters make the state space infinite (reported as INCONCLUSIVE).
* Only whole-system stuttering at *terminal* states is modelled; fairness is per process or per statement, not per message.
* Partial-order reduction applies to safety checking only (it is not stutter-safe for arbitrary LTL).
