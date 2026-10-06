# Milner

An ML-family language with Hindley–Milner type inference, algebraic data types and exhaustiveness
checking, built from scratch in Go (standard library only).

**Status: Phase 2 (core build) complete.** The four required features work end-to-end:

| # | Feature | Where |
|---|---------|-------|
| 1 | Lexer + parser (let/let rec/and, fun/function, if, match with guards/or/as patterns, tuples, lists, operators, annotations, `type` decls, nested comments, positioned errors, layout rule for top-level declarations) | `internal/syntax` |
| 2 | Hindley–Milner inference: let-polymorphism with level-based generalisation, occurs check, value restriction (weak `'_a` variables), annotations, span-accurate errors, "did you mean" | `internal/types` |
| 3 | Algebraic data types + Maranget exhaustiveness/redundancy analysis with concrete witnesses | `internal/types`, `internal/check` |
| 4 | Evaluator with proper tail calls, mutual recursion, refs, prelude written in Milner, `run` / `check` / `type` / `repl` CLI | `internal/eval`, `internal/lang`, `cmd/milner` |

```
go build -o milner ./cmd/milner
./milner run -v examples/…           # (examples arrive in Phase 4)
./milner type 'fun f g x -> f (g x)' # ('a -> 'b) -> ('c -> 'a) -> 'c -> 'b
./milner repl
go test ./...
```

See [PLAN.md](PLAN.md) for the plan and remaining stretch features.
