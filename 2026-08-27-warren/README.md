# Warren

A from-scratch Prolog implementation that compiles clauses to real
[Warren Abstract Machine](https://en.wikipedia.org/wiki/Warren_Abstract_Machine)
(WAM) instructions — not an interpreter that re-walks source terms on
every call, but a real compiler emitting a real instruction set, run on
a tagged heap with a register file, an environment stack, and a
choice-point stack. This is the execution model behind SWI-Prolog, GNU
Prolog, and SICStus — invented by David H.D. Warren in 1983 and still,
in descendant form, how production Prolog systems actually work.

## What it is

- **A real compiler.** Clauses are compiled once into WAM instructions
  (`get_var_x`, `put_struct`, `call`, `allocate`, `cut`, …), not
  re-matched against source terms at every call. First-argument
  indexing filters non-matching clauses before a choice point is even
  created.
- **A real abstract machine.** A tagged heap (`REF`/`STR`/`FUN`/`CON`
  cells — a bound variable is a reference *chasing through* to its
  value, not a slot holding one), an X-register file, an environment
  stack for permanent variables, and a choice-point stack that makes
  backtracking a matter of restoring saved state and jumping, not
  re-running anything.
- **A second, independent implementation as an oracle.** A deliberately
  naive tree-walking SLD-resolution interpreter (`golden.py`) computes
  the same answers a completely different way — no compilation, no
  heap, no registers — and every test in this project checks the
  compiled WAM's answer against it, solution for solution. This is the
  same "two implementations must agree" pattern this repo has used
  before (Silicon's pipeline-vs-golden-model CPU simulator), applied to
  logic programming instead of hardware.
- **A meta-call mechanism built on the compiler, not around it.**
  `findall/3`, `\+/1`, `catch/3`, and `call/N` all work by compiling
  their goal argument as a throwaway single-clause predicate and
  running it through the *same* WAM dispatch loop, recursively — which
  is genuinely how real WAM-based systems implement meta-calls, and is
  why control constructs (`,`/`;`/`->`) work identically whether they
  appear in a clause body or inside a `findall`'s goal.

## Why this, today

This repo has built interpreters (Coil's bytecode VM, Kiln's WASM
toolchain), a JIT straight to x86-64 machine code (Ember), a Hindley-
Milner type inferencer (Unify), and a cycle-accurate CPU pipeline
simulator (Silicon) — but never **logic programming**: a program that
specifies *what* a valid answer looks like, not *how* to compute it,
executed by a search procedure (SLD resolution via unification and
backtracking) rather than direct evaluation. That's a different
programming paradigm from every prior "language" build here, not just
different syntax on the same imperative/functional substrate — and it
comes with a genuinely different memory model to build (a term-graph
heap with trail-based backtracking, instead of a call stack or a
value-holding register file) and the repo's favorite verification trick
in a new shape (see "golden-model oracle" above).

It also turned out to be an unusually good showcase for *why* that
oracle pattern matters: every one of the interesting bugs in this build
(documented in full in `REVIEW.md`) was the compiled WAM silently
computing a *different, wrong* answer from the golden model — a choice
point's saved continuation captured one line too early, a register
lifetime bug that only manifested when two nondeterministic calls
chained together, a generator getting garbage-collected mid-computation
and clobbering machine state — never a crash. Without a second,
independently-correct implementation to diff against, several of these
would have shipped silently.

## How to run it

```bash
cd 2026-08-27-warren

# Run a query against a file and print the first solution:
python3 -m warren run examples/family.pl "ancestor(tom, X)."

# ...or every solution:
python3 -m warren run examples/family.pl "ancestor(tom, X)." --all

# The classics:
python3 -m warren run examples/queens.pl "count_solutions(8, C)."
python3 -m warren run examples/zebra.pl "zebra(Owner, WaterDrinker, Street)."
python3 -m warren run examples/expr_dcg.pl "calc(['(',3,+,4,')',*,2],V)."

# Interactive top-level:
python3 -m warren repl examples/family.pl

# Step through a real captured WAM execution trace in your browser:
python3 -m warren viz examples/family.pl "ancestor(tom, X)." --out trace.html

# Run everything (unit + differential test suite):
python3 -m warren test
# ...or the full end-to-end demo/verification script:
bash demo.sh
```

No dependencies beyond Python 3 stdlib for the engine itself; the
visualizer's screenshot verification during development used the box's
pre-installed Playwright/Chromium, but the generated HTML has no
external dependencies of its own (open it directly, no server needed).

## Full feature list

**Required:**
1. **Tokenizer + operator-precedence parser** for real Prolog syntax —
   the standard operator table, list sugar (`[H|T]`), quoted atoms,
   `0'c`/`0x`/`0o`/`0b` numeric literals, block and line comments.
2. **WAM compiler + abstract machine** — tagged heap, register
   allocation (temp X registers via a "reuse the argument register"
   optimization + real permanent-variable analysis for Y registers
   across call boundaries), first-argument clause indexing,
   cut/if-then-else/disjunction all compiled to real choice-point
   machinery (see `compiler.py`'s module docstring for the honest list
   of simplifications relative to a textbook implementation).
3. **Built-in predicate library** — unification control, arithmetic
   (`is/2` + comparisons over a full expression evaluator), cut,
   if-then-else, negation as failure, `findall/3`/`forall/2`/
   `aggregate_all/3`/`bagof`/`setof`, a mutable clause database
   (`assert`/`retract`/`clause`), `catch/3`/`throw/1`, `call/1..8`,
   plus a list/control library (`append`, `member`, `maplist`, `foldl`,
   `sort`, …) written in **real Prolog** in `bootstrap.pl` and compiled
   by Warren's own compiler at startup — not hardcoded in Python.
4. **Golden-model differential oracle** — an independent tree-walking
   SLD-resolution interpreter, cross-checked against the compiled WAM
   across 65+ test queries including the Zebra puzzle and N-Queens.

**Stretch:**
5. **Interactive HTML WAM execution visualizer** (`warren viz`) — steps
   through a real captured trace (every instruction actually executed
   for that query, not a synthetic example): the instruction stream,
   live heap/trail/choice-point-stack size, and the pending choice
   points at each step. Self-contained, no server, screenshot-verified
   in real headless Chromium with zero console errors.
6. **DCG (`-->`) support** — real difference-list translation, used to
   build and run an actual arithmetic-expression parser
   (`examples/expr_dcg.pl`: tokenized input → AST → evaluated result,
   with correct operator precedence and parenthesization).

## Verdict

Shipped: 4/4 required + 2/2 stretch. Adversarial review found and fixed
10 real bugs (6 in the WAM's choice-point/register-lifetime machinery,
caught only by the golden-model oracle disagreeing with the compiled
answer; 4 more in a fresh hostile pass — a numeric standard-order bug,
raw tracebacks on ordinary user mistakes, and a real recursion-depth
limitation, all detailed with root cause and fix in `REVIEW.md`).
82/82 tests green (unit, differential, DCG, visualizer) plus `demo.sh`'s
15 end-to-end CLI checks. Known, disclosed (not silently worked around)
limitations: no occurs-check (matches real Prolog's default), no true
ISO soft-cut for `*->`, no last-call optimization (deep recursion costs
environment-stack space, not Python call-stack depth — tested to 20,000
calls) — see `REVIEW.md`'s final section for the honest list.

## Where a human could take this next

- **Real last-call optimization**: reuse the current environment frame
  for a genuine tail call instead of always allocating a fresh one —
  the textbook WAM optimization this build deliberately skipped for
  simplicity (see `compiler.py`).
- **Static clause indexing**: compile first-argument (and deep)
  indexing into real `switch_on_term`/`switch_on_constant`/
  `switch_on_structure` instructions at compile time instead of
  filtering candidates at call time — same net effect, closer to how
  production systems actually do it, and it would open the door to
  proper multi-argument indexing.
- **Attributed variables / constraint support** (CLP(FD) is the classic
  next step for a hobby Prolog — the heap/trail model here is exactly
  the substrate real implementations build it on).
- **Tabling (SLG resolution)** for programs with left recursion, which
  plain SLD resolution (this build, like most textbook Prologs) can't
  handle.
- **A proper occurs-check option** (`unify_with_occurs_check/2`) and a
  cycle-safe pretty-printer/writer for the terms that occurs-check-free
  unification can legitimately produce.
- **Iterative (non-Python-recursive) term-walking bridge functions**
  (`copy_term`, `reify`, `unify`, the pretty-printer) to remove the
  recursion-depth ceiling on very long lists documented in `REVIEW.md`
  finding #10 — the real fix, of which the current recursion-limit bump
  is a disclosed mitigation, not a substitute.
