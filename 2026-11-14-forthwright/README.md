# Forthwright

A complete **Forth** in dependency-free JavaScript whose twist is **static stack-effect inference**.

Forth is untyped and stack-based, so the classic bug is a wrong stack effect that only shows up at runtime as
garbage or an underflow three calls away. Forthwright compiles every word to a small IR and runs an *abstract
interpreter* over it to **prove each word's effect** — `( x1 x2 -- y )` — verify it against your own
`( a b -- c )` comment, and **reject** branch, loop and return-stack imbalance at compile time. Execution can be
recorded and scrubbed **backwards** in a time-travel debugger. No build step, no dependencies.

```
: leaky ( a b -- a )  over + swap ;
error (line 1): stack effect mismatch in LEAKY: the comment ( a b -- a ) promises 2 in / 1 out,
                but the body actually takes 2 and leaves 2
```

## Run it
Needs Node ≥ 18 (developed on 22). The IDE needs only a browser.

```bash
node cli.js run examples/demo.fth          # run a program
node cli.js -e '2 3 + .'                    # one-liner
node cli.js repl                            # interactive
node cli.js effects examples/demo.fth       # inferred effect of every word
node cli.js see examples/demo.fth fact      # disassembly (add --source for pre-optimization IR)
node cli.js trace examples/demo.fth --max 50  # per-op trace with data stack
node cli.js profile examples/demo.fth       # ops executed per word
node cli.js test                            # Forth conformance suite (written in Forth)
./verify.sh                                 # everything: unit, conformance, fuzz, headless-browser UI
open web/index.html                         # the IDE (double-click works; it's static files)
```
Flags: `--no-opt` disables the optimizer, `--lax` downgrades analyzer errors to warnings.

## Features
**Core**
1. **Forth engine** — IR compiler + iterative VM (explicit call stack, so deep recursion is a Forth error, not a JS
   crash). ~130 words: stack ops, 32-bit wraparound arithmetic with floored division, `*/` with a 64-bit
   intermediate, `UM* M* UM/MOD FM/MOD SM/REM`, byte-addressed memory, `IF/ELSE`, `BEGIN/WHILE/REPEAT/UNTIL/AGAIN`,
   `DO ?DO LOOP +LOOP LEAVE UNLOOP I J`, `CASE/OF`, `RECURSE`, `VARIABLE CONSTANT VALUE TO`, `CREATE … DOES>`,
   strings (`." S" TYPE COUNT COMPARE`), `' ['] EXECUTE`, `[ ] LITERAL`, user `IMMEDIATE` words, `HEX/DECIMAL/BASE`.
2. **Stack-effect inference** — CFG abstract interpretation. Proves `in/out` for every word; checks declared
   comments (incl. recursion via the declared effect); rejects IF/ELSE/CASE mismatch, loops that grow or shrink the
   stack, differing `EXIT` depths, unbalanced `>R`/`R>`; literal `n PICK/ROLL` handled exactly; value-dependent
   words (`?DUP`, `EXECUTE`, computed `PICK`) are labelled *dynamic* instead of guessed. `NO-CHECK` is the escape hatch.
3. **Time-travel tracer** — records the machine state before every op; step forward/back, scrub, play, jump;
   output-so-far follows the cursor; the editor gutter highlights the source line being executed.
4. **Web IDE** — editor with line gutter and error markers, console + REPL (history), live data/return stack
   visualisation, word browser (effect + *verified ✓ / inferred / dynamic* badges, filter, built-ins toggle),
   disassembly view, trace tab, profiler, example gallery (including three that the analyzer *rejects* on purpose).

**Stretch**
5. **Optimizer** — constant folding, dead-branch removal, peepholes, constant/variable → literal, inlining of small
   straight-line words (early binding preserved). IDE and `see` show source vs optimized IR. Never changes the
   analyzer's verdict (analysis runs on the source IR) and is differentially fuzzed against unoptimized runs.
6. **Conformance suite written in Forth** — `T{ … -> … }T` harness (itself Forth, running on Forthwright) with 160
   tests; a negative control proves the harness detects failures.
7. **Profiler** — ops and calls per word, bar chart in the IDE.
8. **Share links** — the program is base64-encoded into the URL hash (unicode-safe).

## Verification (all run by `./verify.sh`)
| Layer | What |
|---|---|
| `test/run.js` | 65 checks: engine, errors, analyzer (20), optimizer (10), tracer/profiler (8), CLI incl. exit codes and REPL, every IDE example |
| `test/forth/*.fth` | 160 conformance tests in Forth |
| `test/fuzz.js` | random words: whenever the analyzer **accepts**, running it on sentinel-padded stacks must consume exactly `in`, leave exactly `out`, and not touch deeper cells; plus optimizer on/off must agree (≈15 k runs / 3 seeds) |
| `test/review.js` | one regression per finding in [REVIEW.md](REVIEW.md) |
| `test/ui.js` | 18 headless-Chromium checks: REPL, trace scrub/keys/play, share link round-trip, runaway programs, XSS-inertness, 360 px layout |

## Why I built this today
Nothing in the ledger touches Forth or stack machines, and the problem is a real compiler problem hiding in a toy:
the join-point dataflow over IF/ELSE/loops is small enough to get *provably right* in a day (the fuzzer is the
proof), and the IR that makes analysis easy also makes the optimizer, disassembler and time-travel tracer almost free.
The analyzer even earned its keep during the build: it caught two bugs in my own example programs.

## Honest limits
- Not ANS-complete: no `POSTPONE`, locals, `CATCH/THROW`, double-cell words beyond a handful, file I/O.
- Recursive words are only *verified* with a declared effect comment; without one they are "dynamic".
- Rejecting `EXIT` paths of different depth is deliberate but will annoy people who like `?DUP`-style tricks.
- Cells are 32-bit; memory is a fixed 256 KiB.

## Where a human could take this next
- **Type-ish inference**: extend the abstract domain from depth to `{int, addr, xt, flag}` and catch `@` on a flag.
- **Polymorphic effects** (`?DUP`, `PICK`) via conditional effects `( x -- x x | x )` and path-sensitive analysis.
- **`POSTPONE`/`CATCH`/`THROW`/locals** for ANS conformance; run the official Forth-2012 core test suite.
- **Native backend**: lower the IR to WebAssembly (the stack discipline maps almost 1:1) and compare with the VM.
- **IDE**: memory/dictionary inspector with write-watch in the trace, breakpoints, source-mapped inline effect hints.
- **Language server**: surface inferred effects as hover/inlay hints in any editor.

Docs: [PLAN.md](PLAN.md) · [REVIEW.md](REVIEW.md)
