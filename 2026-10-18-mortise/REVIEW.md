# REVIEW — adversarial pass over Phase 2

I attacked the engine as a hostile reviewer: read every code path for races and nil
dereferences, then wrote failing reproductions (`internal/build/review_test.go`, plus
CLI/parser tests) before fixing anything. A randomized property test (25 random DAGs ×
6 rounds of random edits × random `-j`, cache on/off: incremental result must equal a
from-scratch build, and a second build must be a no-op) and a 600-target stress build were
added as bug-hunting tools; both passed under `-race`.

## Findings (all fixed)

| # | Severity | Finding | Reproduction | Fix |
|---|----------|---------|--------------|-----|
| R1 | **crash** | Changing a recipe when a previously *discovered* dependency is itself a generated target made `decide()` read that unfinished task's `res` → nil-pointer panic (and a data race). Dynamic deps are only awaited when the recipe is unchanged, but `decide` still inspected them. | `TestR1_CommandChangeWithGeneratedDynamicDep` (SIGSEGV) | discovered deps are only evaluated while the recipe hash matches; otherwise "command changed" already decides the rebuild |
| R2 | UX | `[n/total]` could print `[6/5]` when run-time-discovered tasks joined the build | `TestR2_ProgressNeverExceedsTotal` | total grows with the started counter |
| R3 | UX | A dependency that is a *directory* was reported as "no such file"; the CLI then "suggested" an unrelated target | `TestR3_DirectoryDependencyMessage`, CLI session | dedicated message pointing to `$(glob dir/**/*)`; no suggestion |
| R4 | correctness | Output of successful commands went to stderr; `mortise run > out.txt` lost program output | `TestR4_OutputStreams` | success → stdout, failure → stderr |
| R5 | safety | A rule could target `.mortise/db.json` and corrupt Mortise's own state | `TestR5_StateDirIsReserved` | targets under `.mortise/` rejected with a positioned error |
| R6 | correctness | `X = a b  # comment` kept the comment in the value; `t: d # why` created deps named `#` and `why` | `TestTrailingComments` | comment stripping (outside `$( )`, `\#` escapes) for non-recipe lines |
| R7 | UX | Phony targets such as `run` buffered all output until exit — a server or test run looked hung | manual | phony recipes stream live (output writers are mutex-wrapped so lines never tear) |
| R8 | UX | `mortise -j4 clean` / `-C dir clean --all` treated `clean` as a target: command words were only recognised as `args[0]` | `TestCLIDryRunAndClean` | flags and command words can be interleaved |
| R9 | UX | Ctrl-C printed "1 skipped" and exit 1 with no hint | manual SIGINT | prints `interrupted`, exits 130; children are killed by process group and partial outputs removed |
| R10 | UX | Absolute target paths inside the project silently built nothing | manual | normalised to project-relative paths |

## Attacks that held (kept as regression tests)
touch-without-change (no rebuild) and old-mtime-new-content (rebuild) · tampered and
deleted outputs · changed/added/removed dependencies · diamond graphs run the shared node
once · `-jN` is never exceeded (measured with overlapping lock dirs) · fail-fast kills a
running `sleep 5` within 3 s · `-k` builds siblings and skips dependents · partial outputs of
failed commands deleted and no trusted record left · missing declared output / missing
depfile are errors · corrupt DB is discarded with a warning · concurrent `mortise` in one dir
is refused by `flock`.

## Known limitations (documented, deliberately not "fixed")
* File names containing spaces cannot be written in a Mortisefile.
* Recipes are trusted to declare their inputs (static or via `@depfile`). Undeclared inputs
  (env vars, `/usr/include`) are invisible, as in Make/Ninja; a hermetic sandbox is out of scope.
* The action cache keys on (recipe, declared inputs) and verifies discovered inputs through
  manifest entries — the same "direct mode" trade-off ccache makes.
* Phony prerequisites order a build but never invalidate their dependents.
* `$(shell …)` runs at parse time (even for rules you do not build).
