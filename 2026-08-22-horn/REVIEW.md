# Adversarial review

Hostile-reviewer pass over the Phase 2 core build: hunting for bugs, broken
edge cases, ugly UX, and lazy shortcuts. Every issue found here was fixed
before moving on to Phase 4; each entry below names the concrete input that
triggered it and the fix, not just a description of the class of bug.

## Found and fixed

### 1. `query_vars` recursed over the raw term tree -- crashed on any query built from a long list literal
`horn/repl.py`. Before: `query_vars` walked a query's variables with plain
Python recursion over `.args`. A Horn list is a chain of nested `./2`
compounds one level per element, so a query like
`length([0,1,...,4999], N).` produced a term 5000 levels deep, and simply
asking "what variables does this query mention" (called on the *main*
thread, before the query ever reaches the big-stack worker thread in
`runstack.py`) blew Python's default recursion limit with a raw
`RecursionError` traceback -- before the engine itself ever got a chance to
run. Triggering input: `horn query file.horn "length([0,1,...,4999], N)."`
Fix: rewritten as an explicit-stack iterative traversal (`horn/repl.py`).

### 2. `nth0/3` and `nth1/3` raised an instantiation error instead of searching when the index was unbound
`horn/stdlib.horn`. The original definition guarded with `N > 0` before
recursing, which only works when `N` is already bound -- exactly the
"find the element at a known index" direction. Asking the reverse, legitimate
question ("what index is `b` at?") via `nth0(N, [a,b,c], b).` evaluated
`N > 0` against an unbound `N` and raised
`instantiation_error: arithmetic expression has an unbound variable`
instead of searching and returning `N = 1`, breaking the "runs backwards
too, for free" promise every other stdlib predicate keeps. Fix: rewritten to
compute the index *after* recursing (`nth0(N0, T, X), N is N0 + 1`), which
resolves correctly in both directions; re-verified `nth0(2, Houses, X)` still
works in the (unchanged) Zebra puzzle and every other forward use.

### 3. `format_term`'s cyclic/deep-term guard didn't actually engage before Python's recursion limit did
`horn/terms.py`. With the occurs check off (the default), `X = f(X).`
successfully builds a genuinely cyclic term -- correct and intentional, that
unification succeeding is exactly what "occurs check off" means. But
printing it (`write(X)`, or just displaying a query's bindings) crashed with
a raw `RecursionError` instead of the guard's intended graceful `"..."`
truncation, because each level of the guard's own depth counter costs
roughly *two* Python stack frames (the recursive call sits inside a
generator expression passed to `", ".join(...)`), so the counter's
900-per-level threshold arrived well after Python's actual 1000-frame limit
already had. Triggering input: `write(X)` after `X = f(X)`. Fix: lowered the
threshold to 200, with a comment explaining the frames-per-level reasoning
so a future edit doesn't quietly reintroduce the same gap.

### 4. Directives crashed `consult_text` outright -- `ValueError: not enough values to unpack`
`horn/parser.py` / `horn/engine.py`. `parse_program` emitted 3-tuples for
clauses (`("clause", head, body)`) but only 2-tuples for directives
(`("directive", goal)`), while `Engine.consult_text` unconditionally
unpacked `for kind, a, b in parse_program(text)`. Any `.horn` file
containing a `:- Goal.` directive -- valid, documented syntax that simply
had no test or example exercising it -- crashed immediately on load with a
Python-level `ValueError`, not even a clean `HornError`. Fix: directive
tuples now carry a matching third `None` element.

### 5. A malformed query silently dropped everything after the first parsed term instead of raising a syntax error
`horn/parser.py`. `parse_single_term` (used by the REPL and `horn query`)
stopped as soon as it had parsed one complete term and never checked
whether input remained. Typing `foo bar.` at the REPL silently parsed as
just the atom `foo`, discarded ` bar.` with no warning, and then reported
the confusing `existence_error: unknown procedure foo/0` -- correct given
what it parsed, but not what actually went wrong. Fix: `parse_single_term`
now requires the entire input to be consumed (module the one trailing
`.`), raising a clear `syntax_error: unexpected trailing input ...`
naming the offending token and position.

### 6. Abandoned queries leaked trail entries (and their bound `Var` objects) forever in a long-lived session
`horn/cli.py` / `horn/repl.py`. The engine's trail-based backtracking relies
on a clause's own post-solution code (`undo_to(trail, mark)`, right after
its `for _ in solve(...)` loop) to unwind bindings once every solution has
been offered. But the default, and by far the most common, CLI/REPL usage
--"show me one answer, not `--all`" -- takes exactly one solution and
*abandons* the generator without ever asking it for a second one. Nothing
runs a suspended generator's post-loop code on abandonment (Python only
unwinds `finally` blocks on `.close()`/GC, and there wasn't one), so every
single-answer query left a few trail entries permanently un-undone. Harmless
for a one-shot CLI process (the whole engine is thrown away immediately
after), but confirmed with a 200-query loop against one `Engine` --exactly
the REPL's usage pattern -- to leak 600 trail entries with zero cleanup,
unbounded over a long session. Fix: both `cli.py` and `repl.py` now record
`len(engine.trail)` immediately before running each top-level query and
`undo_to()` back to it in a `finally` block once the query is done with,
regardless of how it ended.

## Found and fixed during Phase 4 (the HTML visualizer)

The visualizer runs its own compact tracing evaluator (`horn/viz.py`) rather
than instrumenting `engine.py`'s reviewed hot path directly, so it needed
its own scrutiny -- a differential test (`tests/test_viz.py`) checking it
finds the exact same solutions as the real engine, and an actual headless
Chromium render, both caught real bugs:

### 7. The solution cap was checked but never actually enforced
`horn/viz.py`. `Budget.stop()` compares `self.solutions` against
`max_solutions`, but nothing ever incremented `self.solutions` -- so the cap
silently did nothing until the *much* larger node-count cap eventually
kicked in instead. Caught immediately by the differential test: asking both
the real engine and the tracer for 3 solutions to `queens(5, Qs)`, the real
engine correctly returned 3 and the tracer returned 5. Fix: increment
`budget.solutions` in `build_trace`'s collection loop, before the next
`budget.stop()` check.

### 8. The page's own title/header showed the *last* solution's bindings, not the query
`horn/viz.py`. Same underlying cause as finding #6 (an abandoned generator
never runs its own post-yield `undo_to`), in a new location: stopping the
trace early after collecting enough solutions left the query's variables
bound to whichever branch was last explored. `render_trace_html` formatted
the goal for the page's `<h1>` and `<title>` *after* calling `build_trace`,
so a query for `ancestor(tom, X).` rendered its own header as
`ancestor(tom, jim)` -- the final answer found, presented as if it had been
the literal question asked. Fix: capture the goal's text before exploration
runs (belt), and also have `build_trace` itself `undo_to` its own trail mark
in a `finally` block before returning (suspenders).

### 9. A real headless-Chromium render threw and silently produced an empty page
`horn/viz.py`. `li.classList.add(node.status === 'fail' ? 'collapsed' : '')`
-- when the ternary's false branch (empty string) is taken, `DOMTokenList
.add('')` throws `DOMException` in a real browser (not a Node.js
sandbox or JSDOM, which don't all enforce this). The uncaught exception
aborted `buildNode` partway through building the very first node, leaving
`#tree` completely empty with no on-page indication anything had gone
wrong -- the exact "looks plausible in isolation, breaks the moment you
actually load it" failure mode that's why this project screenshots every
visualizer in real headless Chromium rather than trusting the generated
HTML/JS by inspection. Fix: `if (hasChildren && node.status === 'fail')
li.classList.add('collapsed');` -- only call `.add()` when there is
actually a token to add.

## Also found and fixed during Phase 2 itself (documented here for completeness)

`stdlib.horn`'s first draft of `max_list/2` and `min_list/2` recursed to the
end of the list *before* comparing, and re-ran `max_list` on the same
already-solved sub-list again on every element that didn't improve the
running best -- exponential in the worst case (the maximum sitting at the
very end of the list forces a "re-derive the whole tail" on every step
back). Caught by inspection before it was ever committed, and rewritten in
the accumulator style shipped in `stdlib.horn` (`max_list_/3`,
`min_list_/3`): the running best is threaded forward through the recursion
instead of recomputed backward from it, which is linear.

## Checked and found correct (recorded so the next reviewer doesn't re-walk the same ground)

- **Cut committing across a conjunction, not just to its own call**:
  `b(X) :- a(X), X > 1, !, fail.` against `a(1). a(2). a(3).` correctly
  yields **zero** solutions for `b(X)` -- after the cut commits to `a(2)`,
  the subsequent `fail` does not reopen either `a/1`'s remaining
  alternative (`a(3)`) or `b/1`'s (nonexistent) second clause.
- **Cut scoping does not leak between caller and callee**: given
  `inner(X) :- member(X,[1,2,3]), X>1, !.` and
  `outer(Y) :- inner(Y). outer(other).`, querying `outer(Y)` with all
  solutions correctly yields `Y=2` (from `inner`'s own cut) *and* `Y=other`
  (`inner`'s cut does not also commit `outer`'s own clause selection).
- **Arithmetic comparison vs. structural unification/equality stay properly
  distinct**: `3 =:= 3.0` is true (value comparison), while both `3 = 3.0`
  and `3 == 3.0` are false (int and float are different terms), matching
  the same int/float-sensitive equality `unify/3` already uses.
- **Operator precedence**: `X is 1 + 2 * 3` parses as `1 + (2 * 3)` (=7),
  not `(1 + 2) * 3`.
- **`\=`, `\+`, and `select/3`'s reverse ("insert") mode** all checked
  against hand-verified expected output; no leaked bindings from a failed
  trial unification in `\=`.
- **Deep, legitimate recursion** (not a bug, but load-bearing for the fix in
  finding #1): `length/2` over a 5,000-element list completes correctly
  inside `runstack.py`'s dedicated thread; a deliberately pathological
  50,000-element `numlist/3` fails *cleanly* with a caught `RecursionError`
  rather than the raw segfault that naively raising
  `sys.setrecursionlimit()` alone produces (measured directly during this
  build -- see the docstring in `horn/runstack.py`).

## Known, disclosed limitations (not bugs -- deliberate scope decisions)

- **No `;` (disjunction) or `->` (if-then-else) operators.** Cut is
  transparent through disjunction in real Prolog, which is a real added
  interaction to get right; every demo and stdlib predicate that would
  otherwise want `;` is written instead as multiple clauses with a cut or an
  arithmetic guard (see `max_list_/3`, `numlist/3`). Left out rather than
  shipped half-right.
- **No `assert`/`retract`.** The database is populated by `consult_text` and
  is otherwise immutable for the lifetime of an `Engine`. This is why the
  trail-leak finding above (#6) is a memory-hygiene issue and not a
  correctness one: nothing in this codebase mutates predicate definitions
  at runtime, so no query can observe another query's un-retracted state.
- **The REPL's "is this line the end of the clause" check is a literal
  scan for `.` in the raw line**, not a real tokenizer pass. A `.`
  appearing inside a quoted atom or string on the same line would be
  misread as end-of-clause. Every example and stdlib file avoids this
  entirely (no embedded periods in quoted text), and `parse_single_term`'s
  fix in finding #5 guarantees this can never *silently* produce a wrong
  answer -- worst case is a confusing split that then fails to parse
  cleanly, not a wrong result.
