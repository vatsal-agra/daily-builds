# REVIEW — adversarial pass over Phase 2

Method: hostile probing scripts (edge-case grammars, empty/huge/invalid inputs, CLI misuse),
a **differential fuzzer** (random 3-nonterminal grammars; Earley is the oracle for
acceptance; LR(1)/LALR/SLR must agree with it whenever their tables are conflict-free, and
SLR ⊆ LALR ⊆ LR(1) conflict-freeness must hold; trees must match Earley's unique tree), and
stress inputs of 3 000–60 000 tokens. Every finding below was reproduced before being fixed.

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | Grammar scanner cut a token regex at a `/` inside a character class (`/[^/]+/` → "unexpected ']'"). | bug | Scanner tracks `[...]` classes (incl. leading `]`/`^]`). |
| 2 | `check` reported EBNF helper recursion (`_star1 ⇒ _star1`) as "left recursion" — a false alarm for every grammar using `*`/`+`. | misleading UX | Helpers are filtered; remaining reports say "fine for LR/Earley; blocks LL(1) until `transform`". |
| 3 | No diagnostics for declared-but-unused tokens, duplicate productions (silent reduce/reduce), or precedence pseudo-tokens nothing references. | lazy | Added to `check` report. |
| 4 | `Node.to_json`, `compact`, `==` recursed per tree level → `RecursionError` on a 5 000-term sum; `repr` of a deep tree is unreadable. | bug | Rewritten iteratively; short `__repr__`. |
| 5 | `--format json` with indentation was quadratic on deep trees (hung). | bug | Indent dropped above 2 000 nodes; encoding runs on a deep-stack thread. |
| 6 | Earley `trees()` on a 20 000-token input segfaulted (deep generator recursion on the C stack). | crash | Deep walks run via `run_deep` (big stack, high limit, GC off — cyclic GC rescans the structure each pass → quadratic); single-tree extraction is now an iterative linear-time builder that provably matches the enumerator's first tree. |
| 7 | Earley enumeration copied child lists at every level (O(n²)) and kept a persistent ancestor set per call even for acyclic grammars. | perf | Cons-cell sequences; cycle guard only when the grammar is cyclic. 60 000-token tree: 0.09 s. |
| 8 | Earley completion copied the waiting list for every completed item. | perf | Copy only when `origin == i` (the only case where waiters can be added mid-loop). |
| 9 | `states -m earley`, `gen -m ll1` crashed with a traceback; unreadable input file → traceback. | UX | argparse-level validation; `OSError/UnicodeError/ValueError` reported as `error:` with exit code 2. |
| 10 | The class summary said "smallest LR class: LR(0)" for the precedence-driven expression grammar — true only because `%left/%right` silently resolved the conflicts. | misleading | Summary now says "(given the %left/%right/%prec declarations)". |
| 11 | Conflict reports only gave a shortest prefix, which for dangling-else is not a sentence that exhibits the ambiguity. | weak UX | **Fixed in Phase 4**: `witness` / `conflicts --witness` search for a real ambiguous sentence and print both parse trees (dangling-else → `if ID then if ID then ID else ID`). |
| 12 | (Phase 4) LL(1) parser attached terminal children out of order (terminals were appended at match time, nonterminals at predict time). | bug | Slots reserved at predict time; LL(1) trees now equal LALR trees (tested). |
| 13 | (Phase 4) Writing Parsimony's own DSL as a grammar exposed a real ambiguity (`%prec X` vs `%prec` + atom `X`); caught by `witness`. | grammar bug | Argument made mandatory; the DSL grammar is now SLR(1). |
| 14 | (Phase 5) `Grammar.pretty()` output — what `transform` prints — was not valid DSL (no `;`, `ε` token, no token/precedence declarations) and silently dropped `%prec` overrides. Found by the new round-trip test over every example. | bug | `pretty(full=True)` emits `%token/%skip/%left…/%start`, `%empty`, `;` and explicit `%prec`; round-trips every example. |
| 15 | (Phase 5) `transform` ran Paull's substitution on *all* nonterminals, rewriting rules that were never left-recursive (noise on already-LL(1) grammars). | wasteful/UX | Only nonterminals inside a left-recursive component are touched; LL-friendly grammars report "nothing to do". |
| 16 | (Phase 5) User rules named `_x` and generated EBNF helpers could collide; hidden-ness could not be written in the DSL, so printed helper rules re-loaded as visible. | design gap | Leading-underscore rules are hidden by convention; generated names skip existing names. |

## Things attacked that held up
- LALR lookahead propagation vs canonical LR(1): identical acceptance on ~600 fuzzed grammars;
  the textbook separators (SLR-fails, LR(1)-not-LALR) classify exactly as the literature says.
- ε-rules, nullable chains, `A ⇒+ A` cycles: Earley counts the Catalan numbers
  (1, 2, 14, 132, 1430 for 1/3/5/7/9 operands), reports `inf` for cyclic grammars, and
  completes empty-span items correctly (`S → A A x`, `A → B | ε` has 4 parses).
- Precedence: `%nonassoc` equal-level yields a syntax error entry, `%prec` overrides, yacc's
  last-terminal default is applied.
- Lexer: keyword literal beats identifier regex on ties; line/col across newlines.

## Re-run
`/tmp`-style probes and the fuzzer were re-run after the fixes: zero of findings 1–10 reproduce
(they are now regression tests in Phase 5). Findings 11–13 were closed in Phase 4.

## Mutation check (Phase 5)
To make sure the suite is not decorative: (a) disabling LALR lookahead propagation fails 39 tests;
(b) changing yacc's left-associativity rule (`rl == tl and left → reduce`) fails 2 tests. Both reverted.
