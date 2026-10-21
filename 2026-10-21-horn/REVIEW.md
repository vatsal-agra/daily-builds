# REVIEW — adversarial pass on Horn (phase 3)

Method: I attacked the phase-2 build as a hostile reviewer would — (1) a Go **property fuzzer**
(`horn_test.go`: random terms → `writeq` → re-read → must be a variant; 600k terms over 3 seeds),
(2) ISO-conformity probes for cut/exception/database semantics (`tests/adversarial.pl`, ~170 checks),
(3) stress runs (1M-deep recursion, 10M-iteration loops, runaway recursion, 1M-element findall),
(4) UX walk-through of the REPL and CLI. Every item below was reproduced first, then fixed; the
regression test that now pins it is named in brackets. A fresh run of all suites hits none of them.

## Correctness bugs (found → fixed)

| # | Finding | Repro | Fix / regression |
|---|---------|-------|------------------|
| 1 | **Variable goals inside control constructs leaked cuts.** `G = (!, fail), (G ; true)` failed because `G` was bound at run time and the `!` cut the *clause*. ISO 7.6.2 requires `call(G)` semantics. | `c11` | Clause compiler and `call/N`, `catch/3`, `\+`, `->`, query goals now wrap variable goals in `call/1` (`wrapVarGoals`). `[cut_k, var_goal_cut]` |
| 2 | **Writer produced text that reads back as a different term** (8 distinct bugs, found by the fuzzer): bare `/*` and `.` atoms unquoted; `#->` (adjacent symbol chars glued); prefix op followed by `(` printed as `+(\+)` = functional notation; `-(2^2)` printed as `-2^2` (reads as `(-2)^2`); `+(a:-b)` unreadable (arg > 999); `'|'(a,b)` printed as infix and re-read as `;`; operator atoms as operands (`?- =`) ambiguous; control characters printed raw. | `horn_test.go` | Rewrote operator/operand emission (`writeOperand`, `leftNum`, `termPri`, token-collision spacing, control-char escapes). `TestWriteReadRoundTrip` |
| 3 | `format/2` wrote the text produced *before* an error (`format("~w ~w",[a])` printed `a `). | `fmt_few` | Output is buffered and discarded on error. |
| 4 | Toplevel: a goal that itself calls `read/1` clobbered the query's variable names (both use the stdin reader), so `read(X).` printed `true.` instead of `X = foo(bar).` | REPL | Query variable names are snapshotted before running. |
| 5 | `term_to_atom(T, 'a%comment')` failed: the appended end-dot was swallowed by the comment. | `p54` | Text is terminated with `"\n ."`. |
| 6 | `2 ** -1` raised `type_error(float,2)`; SWI/ISO-float semantics give `0.5` (only `^` is integer-strict). | `a8`-style | `**` with negative int exponent → float. |
| 7 | `member/2` left a choicepoint after the last element so the REPL printed a spurious `false.` after `X = c`. | `--all` run | Re-written with first-argument indexing on the tail (`'$member'/3`). |
| 8 | Writing a cyclic term (`X = f(X), write(X)`) recursed until the Go stack hit its 4 GB limit. | `t7.pl` | Writer depth guard prints `...`. |
| 9 | `bar` was declared as op 1105 *and* 1100; `(a | b)` priority was wrong. | parse probe | Single 1100 definition; quoted `'|'` is no longer an infix operator. |
| 10 | Float exponents printed as `1.5e-07`; shortest round-trip form is `1.5e-7`. | `writeq` | Exponent normalised. |
| 11 | `call(_)` after adding fix #1 looped forever (var wrapped into `call(Var)` repeatedly). | `call_var` | Top-level variable goal now raises `instantiation_error` directly. |

## Performance / resource findings

| # | Finding | Fix |
|---|---------|-----|
| 12 | Every compound cost two allocations (struct + args slice); 40% of nrev time was `mallocgc`. | Single-allocation `comp1..comp4` for arities 1–4. nrev: 3.1 → 3.8 M LIPS. |
| 13 | Runaway recursion took 110 s to hit the memory guard (forced GC on every check, 3 GB limit). | Geometric re-check threshold + 1 GB limit → resource_error in ~20 s; `SetMemoryLimit` keeps GOGC=400 from ballooning. |
| 14 | Trail grew without bound in long deterministic loops. | Var-age filter: only variables older than the newest choicepoint are trailed (verified: 10M-iteration loop stays flat). |

## UX findings

| # | Finding | Fix |
|---|---------|-----|
| 15 | Toplevel printed `_G123`-style variables and `[1,2,3]` without spaces; SWI users expect `[_, _]`, `f(A, B)`. | Toplevel writer: `, ` spacing, `_` for singletons, `_A`… for shared unbound variables. |
| 16 | Answer text printed straight after program output (`hellotrue.`). | Toplevel emits a newline when the output column ≠ 0. |
| 17 | Missing-file error read `Unknown source_sink: 'x.pl'`. | `source_sink `x.pl' does not exist`. |
| 18 | Errors in directives were labelled `Warning:`. | `ERROR:` for exceptions, `Warning:` only for failed directives & singletons. |

## Known limitations (documented, not bugs)
* Cyclic terms: `X = f(X)` is accepted (no occurs check by default, like every Prolog); `==`/unify on two *different* cyclic terms can loop.
* `"text"` is a code list (ISO `double_quotes=codes`), not an SWI string — see README.
* Indexing is first-argument only; no tabling, no attributed variables / CLP(FD).
* Not a module system: `Module:Goal` just calls `Goal`.

## Test oracle disagreement log
Several failures during the pass were *my tests* being wrong, and are recorded so they are not
"fixed" the wrong way later: shared variables between conjoined `t/2` calls (harness now copies the
goal), `(a:-b)` as an unparenthesised argument (a genuine syntax error in ISO), `f(/*)` (a comment
start), `2**3**4` (`**` is `xfx`), a wrong hand-computed 36-digit product.

---

# Second adversarial pass (after the stretch features, phases 4–5)

New attack surface (tabling, strings, hash index, lazy enumeration, tracer) got its own hostile
treatment, plus three *independent oracles* so that the engine is no longer only checked against
my own expectations:

* `tests/difftest.py` — random programs (facts, rules, `!`, `->`, `*->`-free `;`, `\+`, `call/1`,
  `catch/throw`, `findall`, arithmetic guards) solved by Horn **and** by a reference SLD interpreter
  written separately in Python; ordered answer lists must be identical. ~6 000 programs over 15 seeds.
  It found **0 engine bugs** — and several bugs in the reference itself (cut not propagating to the
  callee's remaining clauses, instantiation errors not catchable, `[X]` not evaluable, …), which is
  the expected failure mode of a differential test between two careful implementations.
* `tests/tablediff.py` — random graphs: tabled left-/right-/double-/mutually-recursive reachability and
  `min`-mode shortest paths against a transitive closure and Floyd–Warshall.
* `TestBuiltinsNeverPanic` — every native builtin gets 5 000 random argument tuples (unbound, bigints,
  partial lists, strings, cyclic-looking shapes). Found a real crash on the first run.

| # | Finding | Fix / regression |
|---|---------|------------------|
| 19 | `sort(-1, @<, L, S)` indexed `args[-2]` → Go panic. | domain_error; `TestBuiltinsNeverPanic`. Also: any internal fault inside a query is now converted to `system_error(Msg)` instead of killing the session. |
| 20 | `retract/1` and `clause/2` built *every* matching clause up front; a FIFO queue drained with `retract(queue(X))` was O(n²). | Lazy generator choicepoint (`cpGen`) with one-solution lookahead (so the last clause is deterministic). `queue_fifo` (50 000 items). |
| 21 | `eraseClause` copied the whole clause slice on every retract (O(n²) for bulk deletes). | Mark erased + lazy compaction when more than half are dead; snapshots keep logical-update-view semantics. |
| 22 | Calling `fact(150000, X)` scanned 200 000 clauses linearly. | Per-predicate first-argument hash index, built on demand, maintained on `assertz`, dropped on `asserta`/variable-first clauses. `lookup_200k`, `lookup_det`. |
| 23 | `maplist/include/exclude/partition` left a choicepoint per element (list was not the first argument), so a 1M-element `maplist` kept 1M choicepoints alive. | List-first helper predicates; `det_lambda`, `det_*` tests via the new `'$cp_count'/1`. |
| 24 | Tabling re-evaluated every pass from scratch: all-pairs reachability on a 300-node cycle took 21 s; and a tabled predicate with a side effect ran it twice. | Consumers are *cursors* over the live answer table (see answers appended while they run), and a pass is only repeated if some table actually consumed an incomplete table → 0.29 s; `memo1`. |
| 25 | `term_string/2` had its arguments in the wrong order (SWI is `term_string(?String, ?Term)`). | Fixed; `s_term_string`. |
| 26 | Builtins that only pretended to work (`print_message_lines/3`, `message_to_codes/3`, a debug `tabling_noop`) returned `true` without doing anything. | Removed — an unknown procedure is more honest than a lie. Remaining deliberate no-ops (`style_check/1`, `prompt/2`, `set_stream/2`, `license/1`, `garbage_collect/0`, `use_module/1,2`, `module/2`, `meta_predicate/1`, `multifile/1`, …) are declarations that SWI programs contain and Horn does not need. |
| 27 | `halt` with an open file stream lost its buffered data. | All streams are flushed on every exit path. |
| 28 | `aggregate_all(max(X-Y), …)` raised a type error (always evaluated the term as arithmetic). | Numbers compare numerically, anything else by standard order, as SWI does. |
| 29 | A 20 s hang on runaway recursion (see #13) was still too slow to put in a test. | `HORN_MEM_MB` env var lowers the guard; `verify.sh` asserts a catchable `resource_error(stack)` in 3 s. |
| 30 | Missing "read a line" API made stdin-driven scripts impossible. | `read_line_to_string/2`, `read_line_to_codes/2`, `read_file_to_string/3`, `nb_current/2`, `library(option)`. |
