# Warren — a from-scratch Prolog on a real Warren Abstract Machine

## Concept

Build Prolog the way real Prolog systems are actually built: not by
tree-walking the clause database at query time, but by **compiling clauses
to abstract-machine instructions** and running those instructions on a
register-and-heap virtual machine — the Warren Abstract Machine (WAM),
invented by David H.D. Warren in 1983 and still, in descendant form, the
execution model behind SWI-Prolog, GNU Prolog, and SICStus.

This repo has built interpreters, bytecode VMs (Coil), a WASM toolchain
(Kiln), a JIT straight to machine code (Ember), a type inferencer (Unify),
and a CPU pipeline simulator (Silicon) — but never **logic programming**:
programs that don't specify *how* to compute an answer, only what a valid
answer looks like, executed by a search procedure (SLD resolution) that
finds it via unification and backtracking. It's a different programming
paradigm from every prior "language" build, not just a different syntax on
the same imperative/functional substrate. It also lets us reuse the repo's
favorite verification trick — a second, independent implementation checked
bit-for-bit against the first — in a new shape: a dead-simple tree-walking
SLD-resolution interpreter as the "golden model," cross-checked against the
real compiled WAM across every test program and puzzle.

## Why it's interesting

- **Unification isn't equality-checking**: it's a search for the most
  general substitution that makes two terms identical, itself a small
  algorithm with an occurs-check correctness subtlety (the same one Unify's
  Algorithm W needed, in a different setting: relations instead of
  functions).
- **Backtracking search over a real machine, not the call stack**: WAM
  choice points are explicit heap-resident records (goal pointer, argument
  registers, trail mark, alternative clause pointer) that let the *same*
  machine express both deterministic execution and full nondeterministic
  search with clause indexing and cut — real production Prolog performance
  work is entirely about shrinking or avoiding these records.
- **The heap is a term graph, not a value store**: WAM heap cells are
  tagged (REF/STR/functor) and *point into each other*; a bound variable is
  a REF cell pointing at its binding, unbinding on backtrack is just
  truncating the trail. This is a genuinely different memory model from
  every stack/register VM this repo has built before.
- **Strong, checkable ground truth**: classic logic puzzles (N-Queens, the
  Zebra/Einstein puzzle, family-tree relations, list predicates) have
  known, previously-published unique answers — plus we get a from-scratch
  second interpreter (simple SLD resolution, no compilation) to
  differentially check every query against the compiled WAM, the same
  "two implementations must agree" pattern Silicon used for its pipeline
  vs. golden model.

## Architecture

```
source (.pl text)
   │  tokenizer (atoms, vars, numbers, strings, operators, punctuation)
   ▼
recursive-descent + operator-precedence parser
   │  (handles user-definable infix/prefix/postfix operators: :-, ,, ;, ->,
   │   is, comparisons, +/-/*//, standard Prolog operator table)
   ▼
term representation (Atom, Var, Num, Struct — functor+args, lists as
'.'/2 + '[]' sugar)
   │
   ├──► golden-model interpreter: direct SLD resolution over terms
   │     (naive unification + Python-generator-based backtracking) — the
   │     oracle every WAM answer is checked against
   │
   └──► WAM compiler: clause → real WAM instructions
         (get_/put_/unify_* argument instructions, try/retry/trust_me
         choice-point instructions, call/execute/proceed, first-argument
         indexing (switch_on_term))
              │
              ▼
         WAM abstract machine: tagged heap (REF/STR/CON/functor cells),
         argument registers, environment stack (frames for permanent
         variables), choice-point stack, trail, cut barriers
              │
              ▼
         built-in predicate library (is/2 arithmetic, comparisons, =/2,
         \=/2, ==/2, list predicates, findall/3, assert/retract, cut !,
         negation-as-failure \+, DCG --> translation)
              │
              ▼
   CLI (`warren run file.pl`, `warren repl`, `warren test`, `warren viz`)
              │
              ▼
   interactive HTML visualizer: replays a captured real WAM execution
   trace as a step-through view of heap / trail / choice-point stack /
   current instruction, for a real query against a real program
```

## Feature list

**Required (core, must fully work end-to-end):**

1. **Tokenizer + operator-precedence parser** for real Prolog syntax:
   atoms, variables, integers, strings, lists (`[H|T]` sugar), the
   standard operator table (`:-`, `,`, `;`, `->`, `is`, `=`, `\=`, `==`,
   arithmetic/comparison operators, unary minus), comments, and clause
   (`.`-terminated) reading from a source file.
2. **WAM compiler + abstract machine**: real compiled execution — clauses
   compiled to WAM instructions (not re-interpreted from source terms
   every call), executed on a tagged heap with a trail-based
   choice-point/backtracking stack, environment stack for permanent
   variables, and first-argument clause indexing.
3. **Core built-in predicate library**: unification control (`=/2`,
   `\=/2`, `==/2`, `\==/2`), arithmetic (`is/2` + comparisons over a real
   expression evaluator), cut (`!`), if-then-else (`->`/`;`), negation as
   failure (`\+`), list predicates (`append/3`, `member/2`, `length/2`,
   `reverse/2`, `nth0/3`, …), `findall/3`, and a mutable clause database
   (`assert(z)`/`retract/1`) for stateful programs.
4. **Golden-model differential oracle**: an independent, deliberately
   simple tree-walking SLD-resolution interpreter (no compilation, no
   WAM) that computes the same answers a completely different way, run
   against every test program and puzzle so every WAM answer set is
   checked to agree bit-for-bit with the naive interpreter's.

**Stretch:**

5. **Interactive HTML WAM visualizer**: step through a real captured
   execution trace of a real query — heap cells with their tags, the
   trail, the choice-point stack, and the current instruction — rendered
   client-side from a JSON trace with no server round-trip.
6. **DCG (Definite Clause Grammar) support**: `-->` rules compiled to
   real difference-list-passing clauses, used to build and run an actual
   small grammar (arithmetic expression or sentence parser) through the
   same WAM.

**Bonus (if time allows):** a `repl` with tab-completable predicate
listing and `;`-driven "more solutions?" backtracking, matching real
Prolog top-level UX.

## Verification strategy

- Golden-model vs. WAM cross-check across every example program (family
  trees, list predicates, N-Queens, Zebra puzzle, arithmetic, DCG grammar)
  — same solution sets, same order where order is defined by SLD
  resolution's fixed left-to-right/depth-first strategy.
- Classic puzzles with known, independently-published unique answers
  (Zebra puzzle's "the German owns the fish", N-Queens solution counts for
  small N) as ground truth beyond mere self-consistency.
- Unit tests for the parser (operator precedence/associativity), the
  unifier (including the occurs-check case), the WAM instruction set in
  isolation, and each built-in predicate.
