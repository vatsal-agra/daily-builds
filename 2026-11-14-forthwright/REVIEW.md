# Adversarial review

Method: treat the Phase 2 build as someone else's code. Attack with (a) a soundness fuzzer for the analyzer
(`test/fuzz.js`: accepted words must obey their inferred effect at runtime, and optimizer on/off must agree),
(b) hand-written hostile probes (redefining built-ins, runaway programs, odd comments), (c) Playwright
walk-through of the IDE at desktop and 360 px width, (d) CLI misuse. Every item below has a regression check
in `test/review.js` (R-numbers) or the fuzzer, and **all are fixed**.

| # | Severity | Finding | How found | Fix |
|---|----------|---------|-----------|-----|
| R1 | high | Analyzer ran on *optimized* IR, so constant-folded dead branches made ill-formed words pass — accept/reject depended on `--no-opt`. | fuzzer (121 failures on first run) | Analyze the source IR, then optimize. |
| R2 | high | `: type ... ;` (or `over`, `=`, `drop`, `@`, `!`) silently broke `."`, `CASE/OF`, `VALUE/TO` because the compiler looked helpers up by name. | probe | Compiler uses a frozen `core()` table. |
| R3 | high | No runtime ceilings: `begin 1 again` grew the stack to 50 M cells; `begin 65 emit again` built a 50 MB string (would freeze the browser tab). | probe | Stack ceiling, output ceiling, per-UI limits (3 M steps / 200 k chars). |
| R4 | medium | A user-defined `IMMEDIATE` colon word crashed the compiler (`w.fn is not a function`). | probe | Immediate colon words execute on the VM. |
| R5 | medium | Stack comments with parse-time args (`( n "name" -- )`) or alternatives (`n -- n \| 0`) produced false "effect mismatch" errors, making the normal `CREATE … DOES>` idiom unusable. | probe | Quoted args are ignored; `\|`/`...` comments are treated as uncheckable. |
| R6 | medium | `EXIT` inside `DO` leaves loop parameters on the loop stack and corrupts the next `I`. | review of VM | Compile error: write `UNLOOP EXIT`. |
| R7 | medium | `I`/`J` outside a loop only failed at runtime, deep in a run. | fuzzer | Compile-time check against open loops. |
| R8 | low | Errors showed `(line N)` twice; mismatch message read like a riddle ("2 in, 1 out but the body is 2 in, 2 out"); error line pointed at `;` not the culprit op. | UI run-through | Single line; clearer wording; analyzer reports the op's own line. |
| R9 | low | Truncated trace reported an empty final stack (state was reset before capture). | CLI probe | Capture state at the stop point. |
| R10 | low | `forthwright -e` printed a spurious blank line when there was no output. | CLI probe | Fixed. |
| R11 | low | Three of my own bundled examples were wrong (Hanoi forgot to drop 4 cells — **the analyzer caught it**; Collatz example left a `DO` open; the Tour's `fib(20)` blew the 20 k-step trace cap so the demo trace was truncated). | UI run-through | Examples rewritten and covered by `test/run.js`. |

## Known limitations (deliberate, documented in README)
- Words whose behaviour depends on runtime values (`?DUP`, `EXECUTE`, `PICK` with a non-literal index, words
  calling them) get effect `?` ("dynamic"); they are still executed correctly, just not statically proven.
- Recursion needs a declared `( … -- … )` comment to be verified; without it the word is "dynamic".
- Different-depth `EXIT` paths are rejected by design (that is exactly the bug class this tool exists to catch);
  `NO-CHECK` is the escape hatch.
- No `POSTPONE`, locals, `CATCH/THROW`, double-cell arithmetic beyond `UM* M* UM/MOD FM/MOD SM/REM S>D`.

## Fresh run-through
After the fixes: fuzz (4 seeds × 2–3 k words), `test/review.js` (10/10), all 8 IDE examples in the browser,
CLI misuse cases, and 360 px layout re-run with none of the above reproducing.
