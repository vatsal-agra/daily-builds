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
| 11 | Conflict reports only gave a shortest prefix, which for dangling-else is not a sentence that exhibits the ambiguity. | weak UX | Phase 4 adds `witness`: searches for a real ambiguous sentence and prints both parse trees. |

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
(they are now regression tests in Phase 5). Finding 11 is closed in Phase 4.
