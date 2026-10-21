# Horn — PLAN

## Concept
**Horn** is a from-scratch, ISO-flavoured **Prolog system in Go** (stdlib only): reader with
user-definable operators, a trail-based backtracking engine with real cut semantics,
exceptions, first-argument indexing and a logical-update-view database, arbitrary-precision
arithmetic, ~200 builtins, a bundled library written in Prolog itself, a consult loader and an
interactive SWI-style toplevel (`?- X = 1.` / `;` for more).

## Why it's interesting
The repo has Datalog (Tarski), SAT, SQL, HM inference, SMT — but never the *general* logic
programming machine with unification, the cut, `catch/throw`, meta-calls and the extra-logical
database. It is the classic "interpreter whose semantics you can't fake": cut barriers,
transparent control constructs, `bagof/setof` with `^`, and exception unwinding through
nondeterminism all have to be exactly right, and thousands of existing Prolog programs
(N-queens, zebra puzzle, meta-interpreters, DCG parsers) are an oracle for correctness.

## Architecture
```
 source text ──► lexer ──► operator-precedence parser ──► Term
                                                          │
 consult: clause compiler (vars→LVar slots, body flattened, ground-subterm sharing,
          first-arg key) ─────► Pred table (atoms carry per-arity *Pred)
                                                          │
 Machine: continuation frames (linked list = free last-call optimisation)
          + choicepoint stack (clauses | alts | goal | catch | barrier)
          + trail with var-age filter (only vars older than newest choicepoint trailed)
          control constructs interpreted in-loop: , ; -> *-> \+ call/N catch/3 !
          det builtins: func(m,args)(bool,error); nondet builtins return solution lists
          sub-queries (findall, forall, ...) = nested barrier + run loop
 library.pl (embedded): lists, apply, assoc (AVL), pairs, aggregate, DCG helpers
 toplevel: REPL, directives, initialization/1, -g goal, uncaught-error messages like SWI
```

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | **ISO reader**: quoted atoms/escapes, `0'c`, 0x/0o/0b, bigints, floats, block comments, `{}`/lists, user `op/3`, prefix/infix disambiguation, syntax errors with line numbers | **required** |
| 2 | **Engine**: unify, backtracking, cut (incl. in `->`, `\+`, `call/N` opacity), if-then-else, soft-cut, `catch/throw` through nondeterminism, first-arg indexing, LCO, logical update view | **required** |
| 3 | **Builtins**: bigint/float arithmetic, type checks, term inspection (`functor/arg/=../copy_term`), atoms & char/code conversion, `sub_atom`, standard order & sorting, `assert/retract`, `findall/bagof/setof` with `^`, `format/2,3`, `read_term`, streams | **required** |
| 4 | **Consult + toplevel**: load files, directives, `initialization`, CLI (`-g`, `-t`), interactive REPL printing bindings & alternatives, SWI-style warnings/errors | **required** |
| 5 | **DCG translation** (`-->`, pushback, `call//N`, `phrase/2,3`) | stretch — shipped |
| 6 | **Library written in Prolog**: lists, apply, pairs, AVL `assoc`, `aggregate_all`, string/atom helpers | stretch — shipped |
| 7 | **Four-port tracer** (`trace/0`, `notrace/0`, Call/Exit/Redo/Fail with depth) | stretch — shipped |
| 8 | **Benchmarks** (nrev LIPS, queens, tak, zebra) | stretch — shipped (`examples/bench.pl`) |
| 9 | `occurs_check` flag, global variables, `succ_or`-style misc | stretch — shipped |
| 10 | **Tabling** with fixpoint evaluation and answer-subsumption modes (added in phase 4) | stretch — shipped |
| 11 | **SWI-style strings** (`string_concat`, `sub_string`, `split_string`…, `"text"` objects) (added in phase 4) | stretch — shipped |
| 12 | **First-argument hash index + lazy clause enumeration** for large fact tables (added in phase 4) | stretch — shipped |

## Verification strategy
Go unit tests for reader/writer/arith; a Prolog conformance suite (`tests/*.pl`, hundreds of
assertions run by Horn itself); classic programs with known answers (queens counts, zebra,
hanoi, primes, meta-interpreter, DCG calculator); cross-check against `swipl` if present.
