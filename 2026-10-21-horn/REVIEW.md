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
