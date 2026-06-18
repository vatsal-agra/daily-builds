# Coil — Adversarial Review (Phase 3)

I attacked my own implementation looking for soundness bugs, GC hazards, and
sharp edges. Findings below, worst first. Every issue is fixed; the
"repro/after" lines are the exact probes I used and re-ran post-fix.

## CRITICAL

### C1 — `break`/`continue` leak loop-body locals → stack corruption
The compiler emitted a raw `JUMP` for `break`/`continue` without unwinding any
locals declared between the jump site and the loop header. Any local declared
inside a loop body that was skipped over by `continue` stayed on the value
stack, shifting every subsequent slot. Because locals are addressed by slot,
later reads returned **stale values**.

Repro (before): the program below returned `500` instead of `800`.
```
fn test() {
    let result = 0; let i = 0;
    while (i < 4) {
        i = i + 1;
        let marker = i * 100;
        if (i == 2) continue;          // leaked `marker`
        result = result + marker;      // then read the wrong slot
    }
    return result;                     // expect 100+300+400 = 800
}
```
`break` had the same defect; it only *looked* fine in simple tests because the
enclosing function's `return` discards the whole frame's stack, masking the
leak when no later local is read.

**Fix:** loop contexts now record the scope depth at loop entry. `break` and
`continue` emit `POP` (or `CLOSE_UPVALUE` for captured locals) for every local
deeper than that depth *before* jumping, without removing them from the
compiler's local table (they remain in scope for code after the jump).
After: returns `800`. ✓

## HIGH

### H1 — `BUILD_LIST` / `BUILD_MAP` / list `+` un-track their elements during GC
These ops removed the element operands from the value stack (or popped them)
*before* allocating the new aggregate. Allocation can trigger a collection
(always, under `--gc-stress`; or when the heap threshold trips). At that
moment the just-removed sub-objects were reachable only from a Python local —
**not a GC root** — so the collector swept them out of the managed heap. They
survived in Python memory (no crash), but became permanently untracked: heap
accounting was wrong and they could never be reclaimed afterward.

Repro (before): `let n=[[1],[2],[3]]; gc(); print heap_size();` printed `2`
under `--gc-stress` (the three inner lists vanished from the heap) vs `5`
normally.

**Fix:** all three ops now build the aggregate and call `allocate()` **while
the operands are still on the value stack** (rooted), then remove them. The
newly allocated object itself is safe because `allocate()` collects *before*
appending the new object to the heap, so it is never swept during its own
allocation. After: `heap_size()` is `5` in both modes. ✓

## MEDIUM

### M1 — No trailing commas in lists / maps / argument & parameter lists
`[1, 2, 3,]` was a syntax error. This is an annoying, arbitrary restriction
for a modern language and makes generated/multi-line literals fiddly.

**Fix:** the comma-separated parsers (`list`, `map`, call args, params) now
accept an optional trailing comma.

## LOW

### L1 — REPL could buffer indefinitely on a malformed multi-line entry
The continuation heuristic treated *any* "expected ..." parse error as
"incomplete, keep reading", because its end-of-input check always returned
true. A genuinely malformed line containing "expected" could trap the REPL.

**Fix:** the REPL now only keeps buffering when the parse error's position is
at the EOF token (i.e. input genuinely ran out), otherwise it reports the error
and resets.

## Verified-good (attacked, found solid)
- Negative list indexing (`a[-1]`), 3-level nested closures, deep recursion
  (VM call loop is iterative — no Python-recursion limit), `1 == 1.0` true
  while `1 == true` false (bool/number kept distinct), division/modulo by zero
  caught, comparison type-checking, undefined-variable / wrong-arity /
  not-callable runtime errors, empty & comment-only programs, multi-frame
  runtime tracebacks with source lines, caret-annotated syntax errors.
