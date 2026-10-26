# Parsimony — a parser-generator laboratory

Write a grammar; Parsimony builds **every classical parsing machine** for it — LL(1), LR(0), SLR(1),
LALR(1), canonical LR(1) and Earley — tells you honestly which class the grammar belongs to, explains
every conflict with a concrete input, parses text, enumerates ambiguous parses, and can emit a
standalone, dependency-free parser module. Pure Python 3.11, standard library only (~2,400 lines of
library, ~790 lines of tests).

```
$ python3 -m parsimony check examples/slr_fails.pg | sed -n '/grammar classes/,$p'
grammar classes:
  ✘ LL(1)    2 conflict(s)
  ✘ LR(0)    10 states, 1 unresolved conflict(s)
  ✘ SLR(1)   10 states, 1 unresolved conflict(s)
  ✔ LALR(1)  10 states, 0 unresolved conflict(s)
  ✔ LR(1)    14 states, 0 unresolved conflict(s)
→ smallest LR class: LALR(1)

$ python3 -m parsimony witness examples/dangling_else.pg
ambiguous sentence: if ID then if ID then ID else ID    (2 parses)
  parse 1: (stmt if ID:ID then (stmt if ID:ID then (stmt ID:ID) else (stmt ID:ID)))
  parse 2: (stmt if ID:ID then (stmt if ID:ID then (stmt ID:ID)) else (stmt ID:ID))
```

## Run it

```bash
cd 2026-10-26-parsimony
./demo.sh                                   # every feature, 18 scripted assertions + the full test-suite
python3 -m unittest discover -s tests -t .  # 84 tests, ~8 s
python3 -m parsimony --help
```

| Command | What it does |
|---|---|
| `check G` | FIRST/FOLLOW/nullable, diagnostics (unreachable, non-productive, left recursion, cycles, unused tokens, duplicate rules) and the LL(1)/LR(0)/SLR/LALR/LR(1) verdict |
| `conflicts G [-m M] [--witness] [-v]` | every unresolved conflict with items, an example prefix and the default action; `--witness` searches for a real ambiguous sentence |
| `states G [-m M] [--grid]` | LR automaton dump (kernel + closure items with lookaheads) or the ACTION/GOTO grid |
| `parse G -e TEXT [-m M] [--format tree\|sexp\|json] [--compact] [--trace] [--recover]` | parse with `lr0 slr lalr lr1 earley ll1` |
| `compare G -e TEXT` | run every strategy on the same input and cross-check accept/reject and trees |
| `ambig G -e TEXT` | Earley: number of parses, minimal ambiguous spans, enumerate trees (detects infinite ambiguity) |
| `witness G` | shortest sentence with two parse trees |
| `ll1 G` / `transform G` | LL(1) table + conflicts / eliminate left recursion & left-factor, printing a re-loadable grammar |
| `gen G -o parser.py [-m M]` | standalone parser module (lexer + tables + driver, stdlib only) |

Exit codes: 0 ok · 1 syntax/lex error or conflicts found · 2 usage / grammar error.

## The grammar language

```
%token NUM /[0-9]+/          # named token (regex; longest match wins, literals win ties)
%skip  /[ \t\n]+/            # discarded between tokens (nothing is skipped unless you say so)
%left '+' '-'                # precedence: later lines bind tighter; %right, %nonassoc too
%right UMINUS                # pseudo-token, used only through %prec
%start expr
expr : expr '+' expr | '-' expr %prec UMINUS | NUM | '(' expr ')' ;
list : (item (',' item)*)? ;      # EBNF: * + ? ( | ) — desugared into hidden helpers
_helper : ... ;                   # rules starting with '_' vanish from parse trees
stmt : error ';' ;                # 'error' = yacc-style recovery point (parse --recover)
```

## Feature list

**Required (all shipped)**
1. **Grammar DSL, lexer generator & analysis** — EBNF sugar, precedence/associativity, `%prec`, hidden rules, line-numbered grammar errors; longest-match lexer with line/col; nullable/FIRST/FOLLOW, reachability, productivity, left-recursion SCCs, `A ⇒+ A` cycle detection, shortest derivations.
2. **LR family table construction** — LR(0), SLR(1), LALR(1) (dragon-book spontaneous/propagated lookahead computation over the LR(0) automaton), canonical LR(1); yacc precedence resolution (incl. `%nonassoc` → error entry); conflict diagnostics with items and example prefixes; automatic grammar-class classification.
3. **Shift-reduce driver** — parse trees (pretty / s-expression / JSON), step-by-step trace, errors with `line:col`, offending token and expected-token set, hidden-rule splicing; iterative everywhere so 20,000-term inputs work.
4. **Earley parser** — ε-rules, left/right/hidden recursion, back-pointer forest: exact parse counting (Catalan numbers check out), tree enumeration, minimal ambiguous spans, infinite-ambiguity detection; 60,000-node tree extracted in 0.1 s.

**Stretch (4 shipped)**
5. LL(1) table, FIRST/FIRST vs FIRST/FOLLOW conflicts, predictive parser with trace, and a grammar **transformer** (Paull left-recursion elimination + left factoring) whose output is a re-loadable grammar.
6. **Standalone code generator** — emitted module is equivalent to the in-process parser (tested on four grammars, error messages included) and runs under `python -I` with no Parsimony.
7. **yacc-style error recovery** — pops to a state that shifts `error`, discards input to a viable lookahead, suppresses cascades; reports *all* syntax errors in one run.
8. **Ambiguity witnesses** + `compare` + a **self-check**: Parsimony's own DSL is written as a Parsimony grammar (`examples/parsimony_dsl.pg`, SLR(1)), compiled to a standalone parser, and used to parse every example grammar. (Writing it exposed a real ambiguity, which `witness` pinpointed.)

## Verification

`./demo.sh` → "demo OK". The suite includes: textbook separator grammars landing in exactly the classes the literature says (SLR-fails/LALR-ok, LR(1)-not-LALR, dangling else); precedence/associativity checked against Python's own `eval` on 300 random expressions; Catalan-number parse counts; a **differential fuzzer** (120 random grammars × 1,000 strings: SLR ⊆ LALR ⊆ LR(1), and every conflict-free table must agree with the Earley oracle on acceptance *and* the unique tree); transform output checked language-equivalent by exhaustive enumeration; generated-code equivalence; full CLI exit-code matrix; and mutation checks (breaking lookahead propagation fails 39 tests). See `REVIEW.md` for the 16 findings the adversarial passes turned up and fixed.

## Why I chose this today

The repo already has regex engines, SQL, a Prolog, compilers, TLS and a hardware compiler — but every one of them hand-writes its parser. Nothing produced parsers. A parser generator is the missing foundation, and it is rich in *real* algorithms (LALR lookahead propagation, canonical LR(1), Earley forests) that are easy to get subtly wrong — which makes differential testing against an independent algorithm (Earley) both possible and convincing.

## Where a human could take this next

- **Semantic actions**: attach Python callbacks / AST builders to productions instead of generic trees (the codegen template has the reduce hook already).
- **GLR / GLL** for ambiguous grammars with a deterministic fast path, and Earley with Leo's right-recursion optimisation (currently quadratic on right-recursive chains).
- **Better conflict explanations**: Bison-style counterexamples that show *both* derivations for LR(1) conflicts (the `witness` search is brute-force over sentences, not a product-automaton search).
- **Table compression** (default reductions, comb vectors) and emitting parsers in Go/Rust/JS.
- **Lexer modes** and indentation-sensitive tokens; Unicode-aware token classes.
- **Incremental / error-tolerant parsing** (tree-sitter style) built on the LR tables.
- Automatic **LL(1) ↔ precedence** conversion that keeps operator precedence when removing left recursion (today `transform` preserves the language but not precedence declarations).

## Layout

```
parsimony/  grammar.py lexer.py analysis.py lr.py earley.py ll1.py transform.py codegen.py witness.py
            tree.py util.py api.py classify.py cli.py
examples/   expr json slr_fails lr1_not_lalr dangling_else(+_fixed) ambiguous nullable ll1_lists recover parsimony_dsl
tests/      test_grammar test_lr test_earley test_ll1 test_tools   (+ helpers)
PLAN.md  REVIEW.md  demo.sh
```
