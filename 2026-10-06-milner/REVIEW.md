# Milner — adversarial review (Phase 3)

Method: attacked the Phase 2 build as a hostile reviewer — hostile inputs by hand (cyclic data, 100k-deep
recursion, annotation edge cases, unterminated tokens, CRLF/BOM, REPL abuse), two generative tests
(a type-directed program generator that checks soundness + progress, and a differential test of the
exhaustiveness checker against brute-force enumeration), and a performance run on 100k-element lists.
Every issue below has a regression test (`internal/lang/review_test.go`, `cmd/milner/main_test.go`, or the
fuzzers) and was fixed; the fresh run-through at the end hits none of them.

## Findings

| # | Sev | Issue | Fix |
|---|-----|-------|-----|
| R01 | **Critical** | `let f x = let g (y : 'a) = y in (fun (z : 'a) -> z) 1` crashed the checker with `internal error: unifying generic variable`: an annotation variable generalised by an inner `let` was reused by a later `'a` in the same declaration. | `annotScope` refuses to reuse a variable that is (or contains) a generic variable and makes a fresh one. |
| R02 | **Critical** | Printing a cyclic value (`let a = ref Nil;; a := N a;; a`) overflowed the Go stack — a *fatal* runtime error that kills the process and cannot be recovered. | `Show` has a nesting-depth limit (64) and an output cap; cyclic values print `...`. |
| R03 | **Critical** | `=` / `compare` on a cyclic structure recursed forever (fatal stack overflow), and on a 100k-element list recursed 200k Go frames deep. | `compare` iterates along list spines / last components, has a depth limit and an operation budget, and fails with a normal runtime error. |
| R04 | High | Non-tail recursion was limited to a depth of 100 000 *evaluator* frames, which is only ~30k Milner calls; `build 90000` died. Each frame cost ~1 KB because the giant `loop` function had a huge Go stack frame. | Split `loop` into `doApp`/`doMatch`/`doLet` (≈2× smaller frames); limit raised to 400 000 evaluator frames (≈130k Milner calls) with a graceful error; verified peak memory ≈ 400 MB at the limit instead of fatal 1 GB overflow. |
| R05 | High | Hole probe (`let f x = _`) panicked: the hole's type contained variables already generalised by the enclosing `let`. | Probe instantiates the hole type as well as each candidate. |
| R06 | Medium | REPL treated any line containing `;;` as the end of input — even inside a string or comment — and ran half a declaration. | `replComplete` lexes the buffer: only a real `;;` token completes an input; unterminated string/comment keeps reading. |
| R07 | Medium | An unexpected Go panic anywhere in a declaration would crash the whole REPL session. | `Session.Step` recovers and reports an `internal` diagnostic; the session survives. |
| R08 | Medium | `let f x = x⏎f 1` (no `;;`) parsed as the application `x f 1` and gave a baffling type error. | Layout rule: a token at column 1 on a new line after an expression-ending token starts a new declaration (indented continuations, `\| arms` at column 1, and lines after `in`/`->`/`=`/operators are unaffected). |
| R09 | Medium | A type error in a list literal underlined the *whole list* and talked about “constructor `::` expects 2 arguments written as a tuple”. | List chains are checked element by element; the error points at the offending element (“all elements of a list must have the same type …”). Constructor tuples are checked component-wise. |
| R10 | Medium | Prelude `sort`/`merge`/`fold_right`/`zip`/`take`/`join` were non-tail-recursive: sorting 100k elements used a very deep Go stack and ran slowly. | Rewritten tail-recursively (accumulator + `rev_append`); GC percent raised in the CLI. Sort of 100k ints ≈ 3 s (was > 4 s with a huge stack). |
| R11 | Low | Misleading note “operand 2 of `!`” for `!f "a"` (the argument belongs to the function *returned* by `!f`). | Positional notes are only produced when the head's declared arity covers the position. |
| R12 | Low | Holes whose type is still unconstrained listed every binding in scope. | A hole with a free type just says nothing constrains it yet. |
| R13 | Low | `(*)` (multiplication section) lexes as a comment start → “unterminated comment” with no hint. | Note: write `( * )`. |
| R14 | Low | Diagnostics whose span ends at the start of a line (unterminated string/comment) rendered a phantom empty line with a stray caret. | Spans ending at column 1 are pulled back to the end of the previous line. |
| R15 | Low | Parse error at a layout boundary said “found `;;`”, which the user never typed. | Described as “the start of a new declaration (a line beginning at column 1)”. |
| R16 | Low | Weak variables (`'_a`) leaked into type-error messages (“found `'_a * '_b`”). | Error printer renders all unresolved variables as `'a`. |
| R17 | Low | Strings could not contain raw newlines. | Allowed (unterminated strings are still reported). |
| R18 | Low | `(!)` could not be written; UTF-8 BOM and CRLF sources were not handled. | `!` added to operator sections; BOM stripped; CRLF covered by a test. |
| R19 | Low | `let x = fun y -> y in x` printed `'_a -> '_a`. | `let … in` with non-expansive bindings and body is non-expansive. |
| R20 | Low | No way to make warnings fatal (CI use). | `--deny-warnings`. |

## Things the review tried and could *not* break

- **Soundness / progress fuzzer** (`fuzz_test.go`): 4 000 type-directed random programs (lambdas, `let`, `match`, lists, options, pairs, higher-order calls); the checker accepts all of them at the intended type and evaluating them never raises an internal error — only the documented runtime errors (division by zero, fuel, stack depth) occur.
- **Exhaustiveness differential test** (`exhaust_fuzz_test.go`): 1 500 random matches over `t * bool * int` with nested/or patterns; the checker's “not exhaustive” verdict and its per-arm “never matches” verdicts agree with brute-force enumeration of 1 098 values every time.
- Value restriction: `ref []` reused at two types is rejected; a failed declaration that refined a weak variable is rolled back (trail undo).
- Static scoping across top-level redefinition (closures keep the binding they were compiled against).
- Proper tail calls: a 1 000 000-iteration accumulator loop and mutual recursion run in constant stack.

## Known limitations (documented, not bugs)

- No relaxed value restriction: `id id` at top level has the weak type `'_a -> '_a` (OCaml prints `'a -> 'a`).
- The literal `-9223372036854775808` is not expressible (use `-9223372036854775807 - 1`); integers wrap on overflow.
- Operators cannot be user-defined; no type aliases; constructor arguments are positional tuples.
- Caret alignment counts runes, not display width (wide CJK/emoji glyphs misalign the caret).
- Evaluation order of function arguments is left to right (OCaml is right to left).
- Nested `match` without parentheses is greedy, as in OCaml.
