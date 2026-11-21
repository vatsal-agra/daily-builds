# Lemma — PLAN

## Concept
**Lemma** is a small *proof assistant* in the Lean / Coq / Agda family, written from scratch in
Python (stdlib only). You state a theorem as a type, prove it as a program (directly, or with
tactics), and a ~600-line trusted **kernel** accepts it only if the resulting term really has that type.

It implements a predicative Martin-Löf style dependent type theory:
`Π` types, λ, a universe hierarchy `Type 0 : Type 1 : …` with cumulativity, user-declared
**inductive families** (Nat, List, Vec, Eq, Fin, And/Or/Exists …) with automatically generated
dependent recursors, strict-positivity checking and ι-reduction, definitional equality by
**normalisation-by-evaluation** with η.

## Why it's interesting
* No repo entry touches dependent types / the Curry–Howard correspondence: the same checker is a
  programming language *and* a theorem prover (proofs are terms; theorems are types).
* The design question that makes it real: *how little must you trust?* Tactics, elaborator and
  parser are all untrusted; every declaration is re-checked by the kernel, and a second,
  algorithmically different **auditor** (named-term substitution, no NbE) re-verifies an exported certificate.
* Generating the dependent eliminator of an arbitrary inductive family (and its computation
  rules) is the heart of every proof assistant — here it's done from scratch.

## Architecture
```
 source.lm ─► lexer ─► parser ─► surface AST ─► elaborator ─► core terms ─► KERNEL (NbE check)
                                     │ `by` blocks                              ▲
                                     └──► tactic engine (metavariables, goals, ─┘ final proof term
                                          unifier) builds a term, never trusted    is re-checked
 kernel env ──► certificate (JSON) ──► auditor (independent checker)      pretty-printer ─► goals / errors / HTML
```
* `terms.py`   – de Bruijn core terms + locally-nameless helpers (fvars, abstract, instantiate)
* `kernel.py`  – environment, NbE evaluator, conversion (β δ ι η), bidirectional checker,
                 inductive-family declaration (positivity, recursor generation), universes
* `lexer.py` / `parser.py` – layout-free surface syntax (Coq-style `.`-terminated tactics)
* `elab.py`    – named surface terms → core terms, `elim … with` case syntax, notation (`=`, infix)
* `unify.py` / `tactics.py` – first-order unifier with metavariables, goal state, tactics
* `pretty.py`  – terms with binder names & infix notation, goal display
* `audit.py`   – independent certificate checker; `report.py` – HTML proof-state report
* `prelude.lm` – the standard library, written *in* Lemma and checked on every start

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | **Dependent type kernel**: Π/λ/universes/cumulativity, NbE conversion with η, definitions (transparent) / theorems (opaque) / axioms | **required** |
| 2 | **Inductive families**: general declaration syntax, parameters + indices, strict-positivity & universe checks, generated recursors (`T.rec`, `T.rec_1`, `T.rec_2`) with ι-reduction | **required** |
| 3 | **Surface language + elaborator**: `def/theorem/axiom/inductive/#check/#eval/#print/infix`, `fun`, `->`, `forall`, `let`, `elim … with` structural case syntax, numerals, `=` sugar, positioned error messages | **required** |
| 4 | **Tactic prover**: `intro intros exact apply assumption refl symm rewrite (←) induction cases constructor have show exfalso left right split` … over metavariable goals with first-order unification; kernel re-checks the result | **required** |
| 5 | **Independent auditor**: export every declaration as a JSON certificate; a second, differently-built checker verifies it | stretch |
| 6 | **HTML proof-state report**: every tactic step with the goals before/after, light/dark | stretch |
| 7 | **Interactive REPL** with `#check`, `#eval`, multi-line proofs and `:goals` | stretch |
| 8 | **Library of proved theorems** in the prelude (add_comm, add_assoc, mul_comm, append_assoc, reverse_reverse, …) | stretch |

## Gates
Every feature has a CLI demo + tests; negative tests (paradoxes, non-positive types, wrong proofs,
tampered certificates) must be *rejected*.
