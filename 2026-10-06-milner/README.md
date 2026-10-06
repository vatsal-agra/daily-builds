# Milner

**An ML-family programming language with Hindley–Milner type inference, algebraic data types, row-polymorphic
records and exhaustiveness checking — built from scratch in Go (standard library only).**

You write programs with no type annotations. Milner infers the most general type of every definition, rejects
ill-typed programs *before* running them with errors that point at the exact offending span, tells you which
cases a `match` forgot (with a concrete example value), and then evaluates the program with proper tail calls.

```text
$ milner type 'fun f g x -> f (g x)'
('a -> 'b) -> ('c -> 'a) -> 'c -> 'b

$ milner type 'fun r -> r.x + r.y'
{ x : int; y : int; .. } -> int

$ cat bad.ml
type shape = Circle of int | Rect of int * int | Dot
let area s = match s with Circle r -> 3 * r * r | Dot -> 0
let total = area (Circle 2) + "3"

$ milner run bad.ml
warning[pattern]: this `match` is not exhaustive
 --> bad.ml:2:14
  |
2 | let area s = match s with Circle r -> 3 * r * r | Dot -> 0
  |              ^^^^^^^^^^^^^ missing: `Rect (_, _)`
  = for example, the value `Rect (_, _)` is not matched by any arm
error[type]: mismatched types: expected `int`, found `string`
 --> bad.ml:3:31
  |
3 | let total = area (Circle 2) + "3"
  |                               ^^^ expected `int`
  = operand 2 of `+`
```

## Run it

```bash
cd 2026-10-06-milner
go build -o milner ./cmd/milner

./milner run examples/queens.ml          # run a program
./milner run -v examples/hm.ml           # ... and print every binding with its type and value
./milner check prog.ml                   # type-check + pattern-check only (--deny-warnings for CI)
./milner type 'map (fun x -> x + 1)'     # type of an expression
./milner explain 'let id x = x in (id 1, id "a")'   # step-by-step inference trace
./milner repl                            # interactive; end inputs with ;;  (:type :explain :env :help :quit)

go test ./...        # unit, property-based, differential and golden tests (~5 s)
./demo.sh            # builds the CLI and checks every feature end-to-end (64 assertions)
./mutants.sh         # plants 19 bugs and demands the test-suite catches each one
```

Requires Go ≥ 1.24. No dependencies. `NO_COLOR=1` disables coloured diagnostics.

## The language in 30 seconds

```ocaml
(* algebraic data types, parametric and recursive *)
type 'a tree = Leaf | Node of 'a tree * 'a * 'a tree

let rec insert x t = match t with
  | Leaf -> Node (Leaf, x, Leaf)
  | Node (l, v, r) -> if x < v then Node (insert x l, v, r) else Node (l, v, insert x r)
(* val insert : 'a -> 'a tree -> 'a tree *)

(* let-polymorphism, higher-order functions, partial application, pipelines *)
let compose f g x = f (g x)
let total = [1; 2; 3] |> map (fun x -> x * x) |> fold_left (+) 0

(* row-polymorphic records: works on any record with (at least) these fields *)
let full_name p = p.first ^ " " ^ p.last
let birthday p = { p with age = p.age + 1 }
type point = { x : int; y : int }          (* type alias *)

(* refs, sequencing, mutual recursion, guards, or/as patterns, annotations *)
let rec even n = n = 0 || odd (n - 1) and odd n = n <> 0 && even (n - 1)
let classify = function 0 -> "zero" | n when n < 0 -> "neg" | _ -> "pos"
```

Also: nested comments, string escapes, `begin … end`, `fun`/`function`, `if` without `else`, operator sections
`(+)`, `(::)`, typed holes `_`, and a standard library (`map`, `filter`, `fold_left`, `sort`, `zip`, `assoc_opt`, `join`, …)
written in Milner itself and type-checked at start-up (`internal/lang/prelude.ml`).

## Full feature list

**Required (core)**
1. **Lexer + parser** for the whole surface language, with positioned errors, a layout rule (a new top-level declaration may start at column 1 without `;;`), nested comments, patterns (nested, or, as, literals, guards), annotations.
2. **Hindley–Milner inference**: let-polymorphism via level-based generalisation, occurs check, the *value restriction* (weak `'_a` variables for `ref []` and other expansive bindings; failed declarations roll back any weak variable they refined), annotations with scoped type variables, readable `'a 'b` type printer, "did you mean" suggestions, errors that carry both the expected type and the specific sub-mismatch.
3. **Algebraic data types + pattern-match analysis**: parametric/recursive/mutually-recursive types, first-class constructors, Maranget usefulness algorithm giving non-exhaustive *witnesses* (`Some None`, `_ :: _ :: _`, `{ b = false; n = _ }`), redundant arms and redundant or-pattern alternatives, refutable `let`/parameter patterns, an analysis budget.
4. **Evaluator + tooling**: compiled-to-closures evaluator with de Bruijn environments, **proper tail calls**, partial/over-application, mutual recursion, refs, polymorphic structural equality/compare (cycle-safe), static scoping across redefinition, graceful stack-overflow and fuel limits, `run` / `check` / `type` / `repl` CLI.

**Stretch (all shipped)**
5. **Row-polymorphic records** — literals, field selection, functional update, punning, record patterns, closed and open (`..`) record types, row unification (Rémy-style), type aliases.
6. **`explain`** — step-by-step inference trace: instantiations, unifications with the variables they bind, generalisation, and the failing unification for ill-typed programs.
7. **Typed holes** — `_` reports the type its context demands and the in-scope bindings that would fit.
8. **Example gallery** — 8 programs with golden outputs (`examples/`): N-queens, symbolic differentiation, BST, stack-VM compiler, JSON parser, **Hindley–Milner inference written in Milner**, refs/closures/queue, records.

**Polish**: coloured diagnostics on a TTY, REPL commands, `--deny-warnings`, `--fuel`, BOM/CRLF-safe input, empty-input behaviour, internal-error containment (a Go panic becomes a diagnostic, the REPL survives).

## How it is verified

| Check | What it proves |
|-------|----------------|
| `go test ./...` (62 test functions, 92 % statement coverage) | parser precedence/layout, ~35 inferred-type cases, ~30 type-error cases, a 28-case exhaustiveness table, ~90 evaluation cases, runtime errors, records, aliases, explain, holes, CLI, REPL, golden examples |
| **Type-directed program fuzzer** (8 000 programs) | every generated well-typed program is accepted at its intended type and evaluates without internal errors (soundness + progress, including records) |
| **Exhaustiveness differential test** (1 500 matches) | the Maranget implementation agrees 100 % with brute-force enumeration for both "non-exhaustive" and "arm never reached" |
| `./demo.sh` | 64 end-to-end CLI assertions across all 8 features |
| `./mutants.sh` | 19 planted bugs (occurs check, generalisation, value restriction, row unification, default matrix, tail calls, de Bruijn indices, scoping …): 19/19 killed |
| [REVIEW.md](REVIEW.md) | 25 issues found by the adversarial reviews and fixed — three were fatal Go stack overflows (cyclic data, deep recursion) |

## Architecture

```
internal/syntax   lexer.go ast.go parser.go diag.go    source → AST; spans; caret/colour diagnostics
internal/types    types.go unify.go infer.go decl.go   HM with levels, rows, aliases, holes; print.go; trace.go (explain)
internal/check    exhaust.go walk.go                   Maranget usefulness → witnesses / redundancy
internal/eval     compile.go machine.go builtins.go    AST → closure tree; TCO loop; primitives
internal/lang     session.go prelude.ml                parse → infer → check → eval pipeline; the prelude
cmd/milner        main.go                              run | check | type | explain | repl
examples/ demo.sh mutants.sh PLAN.md REVIEW.md
```
~6 000 lines of Go (+ ~2 000 lines of tests, 650 lines of Milner).

## Why I built this today

The repo already has dynamic-language VMs, a Datalog engine, a SAT solver and a regex engine, but no *statically
typed* language: nothing where a type system is the product. Hindley–Milner is the best-known "small idea, deep
consequences" algorithm — unification plus levels gives full inference, and then the value restriction, row
polymorphism and Maranget's exhaustiveness check turn it into something that feels like a real language. It also has
unusually crisp correctness properties (soundness, progress, "the checker agrees with brute force"), which made it a
good fit for a build whose bar is *adversarial verification*, not just "it runs".

## Where a human could take this next

- **Relaxed value restriction** (generalise covariant positions, so `id id` is `'a -> 'a`) and **polymorphic recursion** with annotations.
- **Type classes / modules**: today `=` and `compare` are fully polymorphic (they fail at run time on functions); a `Eq`/`Ord` constraint system or a small module system would fix that properly.
- **Exceptions and `try … with`**, plus effect-free `Result` sugar (`let*`); **user-defined operators**.
- **Conflict-free pattern compilation** to decision trees (the evaluator matches arm by arm) and a **bytecode/JIT backend** — sorting 100 k ints currently takes ~3 s.
- **Better diagnostics**: unification-path explanations ("because `x` was used as … on line 3"), multi-span labels, and `explain` as an HTML/graph view of the substitution.
- **Language server**: the spans, holes and trace machinery are already shaped for hover types, go-to-definition and hole-fill suggestions.
- **Mutable arrays, floats, chars, a module/`open` system, a package of larger sample programs.**

See [PLAN.md](PLAN.md) for the original plan and [REVIEW.md](REVIEW.md) for the adversarial reviews.
