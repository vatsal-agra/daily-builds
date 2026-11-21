# Lemma

**A small proof assistant — Lean/Coq/Agda in miniature — written from scratch in Python (standard library only).**

You state a theorem as a *type*, prove it as a *program* (a term, or with tactics), and a ~470-line **trusted kernel**
accepts it only if the proof really has that type. Everything else — parser, elaborator, tactics — is untrusted and
just builds terms for the kernel to check; a second, independently written **auditor** re-verifies the whole development.

```
$ python -m lemma check examples/nat.lm --audit
theorem mul_add_l : forall (a b c : Nat), (a + b) * c = a * c + b * c
theorem mul_assoc : forall (a b c : Nat), a * b * c = a * (b * c)
...
examples/nat.lm: 6 theorem(s) proved, 1 def(s), 0 inductive type(s), 0 error(s)
auditor: ALL 134 declaration(s) verified independently (50 theorem(s), 13 inductive type(s) with re-derived recursors)
```

## Run it

```bash
python -m lemma check examples/*.lm          # check files (exit 1 on any error; errors carry line/column + a caret)
python -m lemma check FILE --audit           # …and re-verify with the independent auditor
python -m lemma check FILE --export c.json   # write a proof certificate;  python -m lemma audit c.json  verifies it
python -m lemma report examples/nat.lm -o r.html   # HTML report: every tactic step with its goals (light/dark)
python -m lemma repl                          # interactive prompt (:help)
python -m lemma eval "6 * 7"                  # evaluate a term
./verify.sh                                   # the whole test + demo suite (≈40 s) → ALL GREEN
```
Needs only Python ≥ 3.10. No dependencies, no network.

## A taste

```lean
theorem add_comm : forall (m n : Nat), m + n = n + m := by
  intro m n. induction m as zero | succ k ih.
  { rewrite add_zero_r. }                       -- goal  n = n + 0  → closed by reflexivity
  { rewrite add.eq_succ. rewrite add_succ_r. rewrite ih. }

def append (A : Type) (xs ys : List A) : List A :=       -- structural recursion with named calls …
  elim xs with | nil => ys | cons x t ih => cons A x (append A t ys) end
                                                          -- … compiles to List.rec and auto-proves
#check append.eq_cons   -- append A (cons A x t) ys = cons A x (append A t ys)    the equation lemmas

inductive Even : Nat -> Type where                       -- an *indexed* family
| even_zero : Even 0
| even_ss : (n : Nat) -> Even n -> Even (succ (succ n))

theorem even_add (n m : Nat) (h1 : Even n) (h2 : Even m) : Even (n + m) := by
  induction h1 as even_zero | even_ss k hk ih.
  { exact h2. }
  { exact even_ss (k + m) ih. }
```
A failing proof stops with the goal state, not a stack trace:
```
fail_demo.lm:13:64: error: unsolved goals:

  a b : Nat
  h : a = b
  ⊢ b = a
```

## Features

1. **Dependent type kernel** — `Π`/`λ`, universes `Type 0 : Type 1 : …` with cumulativity (predicative; `Type : Type` is rejected),
   definitions (transparent, with *smart unfolding* so `add k n` stays readable) / theorems (opaque) / axioms,
   definitional equality βδιη by **normalisation-by-evaluation**, a bidirectional checker, closed-terms-only admission.
2. **Inductive families** — general `inductive` declarations with parameters *and indices* (Nat, List, Vec, Fin, Eq, And, Or, Exists,
   your own). Strict positivity, uniform parameters and a universe bound on constructor fields are checked; the **dependent
   recursor** (`T.rec`, `T.rec_1`, `T.rec_2`: eliminate into `Type 0/1/2`) and its ι-rules are *generated*, never accepted from outside.
3. **Surface language + elaborator** — `def / theorem / axiom / inductive / example / #check / #eval / #print [axioms] / infix[l|r] / prefix`,
   `fun`/`λ`, `->`/`→`, `forall`/`∀`, `let`, `(t : T)`, numerals, `a = b`, user notation, comments (nested), and `elim x return M with | c a b ih => … end`
   — case analysis *and* **structural recursion**: recursive calls by name are checked for decreasing-ness and compiled to recursors with the
   other arguments generalised; each branch also yields an automatic equation lemma `f.eq_c`.
   Errors are positioned, suggest typos, and the parser recovers so one run reports *every* broken declaration.
4. **Tactic prover** over metavariable goals with a first-order unifier (+ type propagation): `intro intros exact apply assumption refl symm
   congr rewrite [<-] [at h] simp [lemmas] induction cases constructor left right split exists exfalso contradiction have show norm unfold revert
   trivial try { … }`. `induction`/`cases` work on parameterised *and indexed* families, revert dependent hypotheses and name
   cases/induction hypotheses. Tactics only build proof terms: **the kernel re-checks every result**, so a buggy tactic cannot prove a falsehood
   (there is a test that sabotages `refl` to prove exactly that).
5. **Independent auditor** (`audit.py`) — a second implementation (named terms, substitution, full δ-unfolding — no code shared with the kernel)
   that re-verifies an exported JSON certificate and **re-derives every recursor and ι-rule** from the constructor types. Tampering with a proof,
   a rule, a recursor type or a constructor (non-positive, universe cheat) is rejected; the repo tests kernel-vs-auditor agreement on 1,500 random terms and 400 mutated proofs.
6. **HTML proof-state report** — each theorem is a collapsible card with every tactic and the goals before/after, error cards, stats, an audit badge, light/dark.
7. **REPL** — multi-line input, `by` proofs end on a blank line, `:load :names :axioms :help`.
8. **Library proved at start-up** — `prelude.lm` (checked by the kernel on every run): `add_comm`, `add_assoc`, `mul_comm`, `add_cancel_l`, `le_trans`,
   `succ_inj`, `zero_ne_succ`, `append_assoc`, `reverse_reverse`, `length_reverse`, `map_append`, … all axiom-free (`#print axioms`).

Soundness hygiene: theorems that depend on axioms are flagged `[uses axiom(s): …]`; failed commands leave no trace in the environment;
no `sorry`/`admit` exists.

## Architecture

```
 source.lm ─► syntax.py (lexer/parser) ─► surface AST ─► elab.py ─► kernel terms ─► kernel.py  (NbE check, trusted)
                                              │ `by`                                  ▲
                                              └► tactics.py (goals, metas, unifier) ──┘ proof term, re-checked
 kernel ─► audit.py export (JSON) ─► audit.py (independent checker)        pretty.py · report.py · repl.py · cli.py
```
Terms are de Bruijn (`terms.py`) with two extra *untrusted-layer* nodes (free variables carrying their type, metavariables) used locally-nameless
style by the elaborator and tactics; the kernel refuses to admit anything that isn't closed.

## Language cheat-sheet

| | |
|---|---|
| types | `Type`, `Type 1`, `A -> B`, `(x : A) -> B x`, `forall (x : A), P x`, `A /\ B`, `A \/ B`, `¬ A`, `a = b`, `a <= b` |
| terms | `fun (x : A) => t`, `f a b`, `let x := v in b`, `elim n return (fun (n : Nat) => T) with | zero => … | succ k ih => … end` |
| commands | `def f (x : A) : T := …`, `theorem t : P := by …`, `inductive T (p : A) : I -> Type where | c : … `, `axiom`, `#eval`, `#check`, `#print axioms t` |
| tactics | each ends with `.`; `{ … }` focuses the first goal; `induction n as zero \| succ k ih.` names the cases |
| no implicits | every argument is explicit (`Eq.symm Nat a b h`); tactics hide it. Equations from `def`s: `add.eq_succ`, `add.eq_zero` … |

## Why I chose this today

The ledger is full of engines that *compute* (compilers, codecs, solvers) but nothing that *proves*. A proof assistant is the one place where
"how little do you have to trust?" has a crisp, checkable answer, and it forces the genuinely hard ideas — dependent elimination of arbitrary
inductive families, normalisation by evaluation, elaboration against unification — into a few thousand lines I can fully hold in my head. The
auditor was the part I most wanted: a proof checker nobody cross-checks is just a program that prints "OK".

## Verification

`./verify.sh` → **ALL GREEN** (27 checks): 148 unit/integration tests (kernel, surface, tactics, 44 adversarial probes, auditor tamper tests, kernel-vs-auditor
differential fuzzing, examples, CLI, REPL, mutation fuzzing for crashes/hangs) plus a scripted demo of every feature. See [REVIEW.md](REVIEW.md) for the
15 issues the adversarial pass found (e.g. `rewrite` matching up to definitional equality and silently making no progress) and [PLAN.md](PLAN.md).

## Known limits

No universe polymorphism (recursors exist for Type 0/1/2; `Eq` is for `A : Type`); `induction`/`cases` need variable indices (no dependent pattern
matching, so `Even 1` is refuted by hand-writing the elimination — see `examples/even.lm`); no mutual/nested inductives; equation lemmas only for a
definition's outermost `elim`; no implicit arguments, type classes or coercions; `simp` is rewriting with equations + given lemmas, not a decision procedure.

## Where a human could take this next

* **Implicit arguments & unification-based elaboration** (higher-order pattern unification) — the single biggest usability win.
* **Universe polymorphism** and a `Prop` sort with proof irrelevance (and then `Decidable`, `Quot`).
* **Dependent pattern matching** (`match` compiled through the recursor with index unification, `no_confusion`) and well-founded recursion.
* **Mutual and nested inductives**, structures with projections and eta, type classes.
* A real **`omega`/`ring`** and a smarter `simp` (congruence closure, AC-rewriting).
* Export the certificate to **Lean 4 / Dedukti** so a *third* checker can verify it; incremental checking and an LSP server that shows goals as you type.
