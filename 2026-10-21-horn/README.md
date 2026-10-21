# Horn — a Prolog system written from scratch in Go

Horn is a complete, ISO-flavoured **Prolog**: reader with user-definable operators, a
backtracking engine with real cut semantics and exceptions, arbitrary-precision arithmetic,
~280 builtin and library predicates, a bundled standard library written in Prolog itself, **DCG translation**,
**tabling** (left recursion terminates; mode-directed `min/max` for shortest paths), a
**four-port tracer**, SWI-style **strings**, an interactive toplevel and a file loader.
Go standard library only — no dependencies, one static binary.

```
$ go build -o horn .
$ echo 'append(X, Y, [1,2]).' | ./horn --all
X = [],
Y = [1, 2] ;
X = [1],
Y = [2] ;
X = [1, 2],
Y = [].
```

## Run it

```
go build -o horn .                      # Go ≥ 1.21
./horn                                  # interactive toplevel (reads stdin; "?- " prompt on a tty)
./horn file.pl                          # consult, then toplevel
./horn file.pl -g main -t halt          # run main/0 and exit (exit code 1 = failed, 2 = raised)
./horn --all < queries.txt              # print every solution when stdin is not a terminal
./verify.sh                             # build + vet + every test suite + transcripts (≈30 s)
```

Options: `-g GOAL` (repeatable), `-t GOAL`, `--all`, `-q`, `--version`, `-h`.
Set `HORN_PROF=cpu.prof` to write a CPU profile.

## Features

**Reader** — full operator-precedence parser: prefix/infix/postfix operators, `op/3`, `{}`/lists,
quoted atoms with every escape (`\n \x41\ \101\ é`), `0'c`, `0x 0o 0b`, `16'FF`, digit groups
(`1_000_000`), big integers, floats (`1.5e10`, `1.0Inf`), block/line comments,
`"strings"`/`` `codes` ``, syntax errors reported with line numbers, singleton and
discontiguous-clause warnings.

**Engine** — continuation-passing machine over a choicepoint stack and a trail; control
constructs are interpreted in the main loop: `, ; -> *-> \+ call/1..8 catch/3 findall`…
* ISO cut semantics (transparent in `, ; ->`, opaque in `call/N`, `\+`, `findall`; variable goals
  become `call/1`),
* `catch/throw` through nondeterminism (catch frames deactivate on exit and reactivate on redo),
* first-argument hash indexing, so `fact(150000, X)` on a 200k-fact table is O(1) and leaves no
  choicepoint; last-call optimisation falls out of the continuation design (10M-iteration loops run in
  constant memory: the trail only records variables older than the newest choicepoint),
* logical update view for `assert/retract`, lazy clause enumeration (`retract(queue(X))` is O(1)),
* resource guard: runaway recursion raises a catchable `resource_error(stack)`.

**Builtins** (~220 native, ~70 in Prolog) — arithmetic with unbounded integers (`X is 2**200`, exact `30!`), all ISO
type checks, `functor/arg/=../copy_term/setarg`, atoms & text (`atom_codes sub_atom atomic_list_concat
split_string format/2,3` with column stops `~t~20|`), standard order (`sort/4 msort predsort keysort`),
`findall/bagof/setof` with `^`, `aggregate_all`, assoc (AVL), global variables, streams (`open/close/
read_term/get_char/peek_char/see/tell`, `with_output_to`, `format(atom(X),…)`), flags, `op/3`,
`listing/portray_clause`, `statistics`, strings (`string_concat sub_string string_chars term_string …`).

**DCG** — `-->` with pushback, `{}//1`, `!`, `\+`, `call//N`, string literals, `phrase/2,3`.

**Tabling** — `:- table path/2.` evaluates left-recursive and mutually recursive predicates to a
fixpoint (SCC-aware, consumers read answers that are still being produced), memoises exponential
recursion (`fib(300)` is instant), and supports answer subsumption: `:- table sp(_,_,min).`
(also `max first last`) and `Name//Arity` for grammars.

**Tracer** — `trace/0` prints Call / Exit / Redo / Fail ports with depth for user predicates and
builtins; a marker choicepoint makes the Fail port exact and deterministic exits print no Redo.

**Toplevel** — SWI-style answers (`X = f(A, B, A)`, `[_, _]`, `X = Y`), `;` for more on a terminal,
errors in the SWI wording including *"However, there are definitions for: append/2, append/3"*.

## Layout

| file | what |
|------|------|
| `term.go` `reader.go` `writer.go` `ops.go` | terms & standard order, lexer/parser, writer (quoting, operators, round-trip safe) |
| `machine.go` `exec.go` | clause compiler, unification, indexing, the run loop, choicepoints, exceptions, tracer |
| `arith.go` | evaluation with `int64` fast path overflowing into `math/big` |
| `builtins_*.go` `dcg.go` `tabling.go` | builtin predicates, DCG translation, tabling |
| `load.go` `main.go` | consult, directives, toplevel, CLI |
| `lib.pl` | the standard library in Prolog (lists, apply, assoc, aggregate, yall lambdas, …) |
| `tests/` `examples/` `horn_test.go` `verify.sh` | ~590 Prolog assertions, differential tests, REPL/trace transcripts, fuzz/property tests, 6 example programs with recorded output |

## Verification

`./verify.sh` (≈ 45 s) runs, and must be entirely green:

| layer | what it checks |
|-------|----------------|
| static | `go build`, `go vet`, `gofmt` |
| Go property tests | 20 000 random terms must survive `writeq` → read (600k in the review pass); arithmetic vs `math/big` on 5 000 random expressions; the standard order is total; unification makes terms identical; **every native builtin survives 250 random argument tuples without a panic** |
| Prolog suites | `core` 256, `adversarial` (ISO cut/exception/database corner cases) 167, `tabling` 22, `strings` 50, `engine` (determinism, resources, 200k-fact tables) 55, `io` (files, streams, consult, ops, format columns) 36 assertions |
| differential | 150 random programs vs an independent Python SLD interpreter (cut, `->`, `\+`, `call/1`, `catch`, `findall`); 30 random graphs of tabled reachability / min-mode shortest path vs closure & Floyd–Warshall |
| transcripts | 6 example programs, a tracer run and 2 REPL sessions diffed against recorded output |
| CLI | `-g`/`-t`, exit codes 0/1/2/3, `read/1` from a pipe, runaway recursion → catchable `resource_error` |

See [REVIEW.md](REVIEW.md) for the two adversarial passes (30 findings, all fixed) and
[PLAN.md](PLAN.md) for the design. Longer runs: `python3 tests/difftest.py 1000 <seed>`,
`HORN_FUZZ_N=200000 HORN_SEED=3 go test -run RoundTrip`, `HORN_PANIC_N=8000 go test -run NeverPanic`.

Speed (this sandbox, one run): naive reverse ≈ 3.5 M LIPS, `tak(18,12,6)` 0.04 s, `fib(24)` 0.13 s —
roughly 5–8× slower than SWI-Prolog's WAM, plenty for the classic programs (zebra, 8-queens,
meta-interpreters), which run in milliseconds.

## Why I chose it today

The repo already had Datalog, SAT, SQL, HM inference, an SMT solver — all *corners* of logic
programming — but never the general machine they are cousins of: unification + backtracking + cut
+ exceptions + the extra-logical database. It is a classic "can't fake it" build: the cut barriers,
`bagof/setof` free-variable semantics, catch frames that must deactivate on exit and come back on
redo, and the logical update view are each easy to get *almost* right. Thousands of existing
Prolog programs serve as an oracle, and the writer/reader pair can be fuzzed against each other.

## Limitations

* No module system (`M:G` just calls `G`), no attributed variables / CLP(FD), no `assoc`-style
  global GC of atoms, no cyclic-term support (writing one is cut off with `...`).
* Indexing is first-argument only; no JIT multi-argument indexing.
* The tracer prints ports but is not interactive (no `creep/skip/leap` prompt).
* `"text"` is an immutable string object (like SWI-7); `set_prolog_flag(double_quotes, codes)` gives
  ISO code lists.
* Toplevel has no line editing/history (pipe through `rlwrap`).

## Where a human could take this next

1. **Compile to a WAM** (or at least first-order bytecode with environment trimming) — the single
   biggest speed-up; the clause compiler already numbers variables and flattens bodies.
2. **Attributed variables → CLP(FD)**: `freeze/2`, `dif/2`, `when/2` first, then a propagation-based
   finite-domain solver (the choicepoint/trail design already has value-trail entries).
3. **Modules and `use_module/2` with real library files**, plus `consult` caching and `include/1`.
4. **SLG resolution with suspension** instead of re-evaluation to fixpoint, WFS (`tnot/1`), incremental tabling.
5. **An interactive debugger** (leash/skip/spy), plus `message_hook` and structured error backtraces.
6. **Cyclic-term safe unification/compare/copy**, and a proper generational atom GC.
7. Run the ISO conformity suite (Inria / Ulrich Neumerkel's) in CI and track the score.
