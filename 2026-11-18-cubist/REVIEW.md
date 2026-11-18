# REVIEW — adversarial pass (Phase 3)

Method: I attacked the Phase 2 build as a hostile user — malformed notation, impossible cubes, absurd
flags, hard states (superflip), tiny `--max`, a concurrent/abusive HTTP client, and the browser player at
phone width and under rapid control use. Everything below was **reproduced** before being fixed.

| # | Severity | Finding (reproduced) | Fix |
|---|----------|----------------------|-----|
| 1 | High | `cubist solve <54-letter facelet string>` silently parsed the string as a 54-move *scramble* (U/R/F/D/L/B are all valid moves) and "solved" a completely different cube. | Positional args that look like a facelet string (54 letters, 9 of each face) are treated as facelets; ambiguity documented. |
| 2 | High | `cubist solve --max 15 <random scramble>` ran past 100 s with no output (exhaustive search for an infeasible length bound). | New `Options.HardLimit` (default 20 s): gives up with a clear error telling the user to raise `--max`. |
| 3 | Medium | Short scrambles got silly solutions: `R U R' U'` was "solved" in 11 moves; a user would rightly think the solver is broken. | If the simplified inverse of the known scramble is shorter than the two-phase answer it is used and labelled `method: inverse-of-scramble` (the UI hides the phase split then). |
| 4 | Medium | `--scramble ""` (explicit empty / already-solved cube) errored "no cube given". | Flag presence is detected with `fs.Visit`; empty scramble = solved cube. |
| 5 | Medium | Negative `--time`/`--target`/`--max` were silently replaced by defaults. | Rejected with an explicit error. |
| 6 | Medium | `serve` had no concurrency cap — N parallel requests = N×3 s of CPU; no read/write timeouts. | Semaphore (NumCPU) with `503 busy`, plus Read/Write/Idle timeouts. |
| 7 | Low | `bench` used the 2 s improvement budget, so a 100-state bench took ~55 s. | bench defaults to 150 ms/state. |
| 8 | Low | Cube occupied only ~55 % of the canvas; looked small, esp. on phones. | Larger projection scale, verified not to clip when orbiting. |
| 9 | Low | Primary button lost its gradient on hover/pause (hover rule overrode it). | Dedicated primary hover style. |
| 10 | Low | Validator parity path (two swapped pieces) and flipped-edge/twisted-corner paths were never covered by an automated test. | Added unit tests for every diagnosis, plus API tests. |
| 11 | Info | Two-phase is *near*-optimal, not optimal (superflip: 21 moves in 2 s, optimum is 20). | Documented honestly in README; not "fixed" — an optimal solver is out of scope. |

Checked and found OK: move parser edge cases (`R2'`, `R'2`, `R3`, curly quotes, parentheses, commas,
unsupported `x`/`M`/wide moves give positioned errors); invalid-cube diagnoses (53 letters, bad letter,
10×R, twisted corner, flipped edge); HTTP method/size/JSON errors; XSS surface (JSON is `json.Marshal`ed so
`<`/`>`/`&` are escaped; user text is only ever set via `textContent`); phone-width horizontal overflow;
step/back/scrub/play/pause/replay state machine; solver result always re-verified (cubie *and* physical).

## Gate re-run
After the fixes every item above was re-executed (see `verify.sh`, which now asserts #1–#6 explicitly):
zero of the listed issues reproduce.
