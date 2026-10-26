# Parsimony — PLAN

## Concept
A **parser-generator laboratory**: write a grammar in a small EBNF dialect, and Parsimony
builds *every* classical parsing machine for it — LL(1), LR(0), SLR(1), LALR(1), canonical
LR(1), and Earley — then tells you honestly which class your grammar belongs to, explains
every conflict with a concrete input prefix that triggers it, parses text, shows the
ambiguity forest, and emits a standalone, dependency-free parser module.

## Why it's interesting
The repo has regex engines, SQL, compilers, languages — but nothing that *produces*
parsers. Yacc/Bison/ANTLR/Lark are the missing link. The interesting parts are the
algorithms: LALR(1) lookahead propagation (dragon-book spontaneous/propagated lookaheads),
canonical LR(1) closure, yacc-style precedence resolution, Earley with nullable handling
and a shared-forest for counting/enumerating ambiguous parses, and grammar
transformation (left-recursion elimination, left factoring) to push a grammar into LL(1).

## Architecture (pure Python 3.11 stdlib, package `parsimony/`)
- `grammar.py`  — grammar DSL parser (`%token`, `%skip`, `%left/%right/%nonassoc`, `%prec`,
  `%start`, quoted literals, EBNF `* + ? ( )` desugaring), `Grammar`/`Production` model.
- `lexer.py`    — longest-match lexer built from the grammar's token table, line/col tracking.
- `analysis.py` — nullable / FIRST / FOLLOW, useless + unreachable symbols, left recursion,
  cycles, shortest-terminal-string derivations (used for conflict examples).
- `lr.py`       — LR(0) automaton; SLR / LALR(1) (lookahead propagation) / LR(1) tables;
  precedence resolution; conflict diagnostics with example prefixes; table-driven
  shift-reduce driver with trace + expected-token errors.
- `earley.py`   — Earley recogniser with back-pointers → forest: count, enumerate, detect
  infinite ambiguity.
- `ll1.py`      — LL(1) table, conflict report, predictive parser; `transform.py` — left
  recursion elimination + left factoring.
- `codegen.py`  — emits a standalone parser `.py` (lexer + LALR tables + driver).
- `tree.py`     — parse tree nodes, pretty/sexp/JSON output.
- `cli.py`      — `python -m parsimony <cmd>`.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Grammar DSL with EBNF sugar, precedence declarations, lexer generation + grammar analysis report (nullable/FIRST/FOLLOW/useless/left-recursion) | **required** |
| 2 | LR family table construction: LR(0), SLR(1), LALR(1), LR(1), with yacc-style precedence resolution and conflict diagnostics with example inputs; automatic grammar-class classification | **required** |
| 3 | Table-driven shift-reduce parser: parse trees (tree/sexp/JSON), step trace, syntax errors with line:col and expected-token set | **required** |
| 4 | Earley parser for arbitrary CFGs: ambiguity detection, parse counting, tree enumeration, infinite-ambiguity detection | **required** |
| 5 | LL(1) tables + predictive parser + grammar transformer (eliminate left recursion, left-factor) | stretch |
| 6 | Standalone parser code generator (emitted module needs no Parsimony) | stretch |
| 7 | Panic-mode error recovery that reports multiple syntax errors | stretch |
| 8 | Self-check: the DSL grammar of Parsimony itself parsed by a Parsimony-generated parser | stretch |

## Verification plan
`unittest` suite + `demo.sh`: textbook grammars with known classes (expression grammar is
SLR; the `S→L=R|R` grammar is LALR but not SLR; the LR(1)-not-LALR grammar; dangling-else
conflict; ambiguous `E→E+E`), cross-checks that all parsers agree on trees, and that
generated code reproduces in-process results.
