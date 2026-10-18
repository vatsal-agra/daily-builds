# Mortise

An incremental **build system** written from scratch in Go (standard library only):
a make-like build language, a parallel scheduler, **content-hash** staleness with
**early cutoff**, **dynamic dependencies** discovered from compiler depfiles, a
**content-addressed action cache**, and tools that tell you *why* anything rebuilt.

```
$ mortise
[1/5] CC   src/strx.c
[2/5] GEN  build/gen/version.h
[3/5] CC   src/main.c
[4/5] CC   src/mathx.c
[5/5] LINK build/app
mortise: 5 ran in 0.09s

$ echo "// a comment" >> include/mathx.h && mortise
[1/2] CC   src/mathx.c
[2/2] CC   src/main.c
mortise: 2 ran, 3 up to date [early cutoff: 2 identical rebuilds, 1 downstream skips] in 0.04s
#   two objects were recompiled, came out byte-identical, so the link was skipped
```

## Run it

```bash
go build -o mortise ./cmd/mortise          # Go 1.24+, no dependencies
cd examples/cproj && ../../mortise          # builds a real C project with gcc
../../mortise why                           # nothing to do -> "up to date"
./../../demo.sh                             # 46 end-to-end checks (also runs go test -race)
```
`./demo.sh` needs `gcc` and `python3`; set `SKIP_TESTS=1` to skip the unit tests.

## The Mortisefile

```make
CC     = gcc
SRCS   = $(glob src/*.c)                      # * ? [..] and ** are supported
OBJS   = $(patsubst src/%.c,build/%.o,$(SRCS))
default build/app

build/app: $(OBJS)
    @desc LINK $@                             # progress text
    $(CC) -o $@ $^

build/%.o: src/%.c                            # pattern rule: $* = stem, $< = first dep
    @depfile build/$*.d                       # read gcc's -MMD output -> dynamic deps
    $(CC) -MMD -MP -MF build/$*.d -c $< -o $@

build/main.o: build/gen/version.h             # extra dep merged into the pattern rule

gen.c gen.h &: spec.y                         # '&:' = grouped outputs, one run makes both
    bison -o gen.c --header=gen.h spec.y

phony test
test: build/app
    ./build/app --selftest
```

* **Variables:** `=`/`:=` (expanded when read), `+=`, `?=`; `$(X)`, `${X}`, `$(X:.c=.o)`. Escape with `$$`.
* **Functions:** `glob patsubst subst dir notdir basename suffix addprefix addsuffix filter filter-out sort strip words firstword if shell`.
* **Automatic variables:** `$@ $< $^ $+ $*`, plus `$(@D) $(@F) $(<D) …`.
* **Directives in a recipe:** `@depfile PATH`, `@desc TEXT`, `@phony`. A leading `-` on a command ignores its failure.
* **Top level:** `default …`, `phony …`, `include file`, `#` comments, `\` line continuation.
* Errors are positioned: `Mortisefile:12: unknown directive "@bogus"`.

## CLI

| command | what it does |
|---|---|
| `mortise [targets]` | build (default targets from `default`) |
| `mortise why [target]` | exact reasons a target would rebuild, as a tree — runs nothing |
| `mortise -n` | dry run: list what would run and why |
| `mortise graph [target]` | dependency graph as Graphviz DOT (stale = red, discovered deps dashed) |
| `mortise stats` | database + cache size, last build's parallelism and **critical path** |
| `mortise watch [target]` | rebuild when an input changes (also notices new files matching a `$(glob)`) |
| `mortise clean [--all]` | delete recorded outputs (`--all`: also the database and cache) |
| `mortise list` | show parsed rules |

Flags: `-j N` / `-jN` parallel jobs (default: CPUs), `-k` keep going, `-f file`, `-C dir`,
`-v` (show commands and up-to-date targets), `-q`, `--no-cache`, `-report out.html`
(self-contained timeline), `-trace out.json` (Chrome/Perfetto trace).
Exit codes: `0` ok · `1` build failed · `2` usage/parse/graph error · `130` interrupted.

## Features (all shipped)

**Required**
1. **Mortisefile language** — variables, 18 functions, `%` pattern rules (with preference for the rule whose inputs exist), merged dependency-only rules, grouped outputs, automatic variables, phony targets, includes, positioned errors.
2. **Parallel scheduler** — one goroutine per task, `-j` slots held only while commands run, fail-fast cancellation that kills whole process groups, `-k`, static cycle detection with the full path (`a -> b -> c -> a`) *plus* run-time wait-for-graph detection for cycles through discovered deps; failed targets lose their partial outputs and leave no trusted record.
3. **Content-hash incremental builds with early cutoff** — SHA-256 of every input and output, not mtimes: `touch` rebuilds nothing, a restored old file rebuilds correctly; recipe changes, added/removed deps, deleted or externally modified outputs are all detected; a rebuilt-but-identical output stops the ripple. Crash-safe atomic database (`.mortise/db.json`) that recovers from corruption.
4. **Dynamic dependencies** — `@depfile` is parsed (`gcc -MMD -MP` syntax: continuations, escaped spaces, `$$`, phony `-MP` rules), the discovered inputs are hashed and stored, and later builds verify them (building any that are themselves generated, first). Headers you never declared still trigger exactly the right rebuilds.

**Stretch**

5. **Content-addressed action cache** (`.mortise/cas`) — keyed by (recipe, declared inputs) with manifest entries that verify discovered inputs ("direct mode", like ccache). `clean` → rebuild restores from cache; reverting an edit hits the old entries; blobs are hash-verified and a corrupt one falls back to running; file modes (executable bit) preserved; grouped outputs supported.
6. **`why` / `graph` / `-n`** — explanation tree down to the root cause; DOT export.
7. **`watch`, `stats`, HTML report, Chrome trace** — critical-path analysis, parallelism factor, a light/dark HTML Gantt with per-bar reasons.

## Verification

* `go test -race ./...` — ~3,760 lines of code, ~1,630 lines of tests: parser/expander/glob, depfile parser, every engine behaviour, a **randomized property test** (random DAGs × random edits × random `-j`: incremental result must equal a clean build and the next build must be a no-op), a 600-target stress build, CLI exit codes, watch mode.
* `./demo.sh` — 46 assertions against a real gcc project (parallel speed-up measured, early cutoff, depfile rebuild precision, cache restore, watch, lock, corrupt DB…).
* `REVIEW.md` — the adversarial pass: 10 findings reproduced with failing tests, then fixed (including a nil-deref crash in dynamic-dep handling).

## Why I chose this today

The ledger already had compilers, databases, VCSes, protocols and runtimes — but nothing about the
thing that *drives* all of them: the build system. Make's mtime model is a classic bug farm, and
the modern answer (Shake/Ninja/Bazel: hashes, early cutoff, dynamic deps, remote caches) is a
compact, deep systems problem whose correctness is directly checkable — "incremental ≡ clean" is a
property you can fuzz.

## Where a human could take this next

* **Hermetic sandboxing** (namespaces / `strace` / `fanotify`) to *prove* declared inputs are complete instead of trusting `@depfile`.
* **Remote cache + remote execution** — the CAS layout and action keys are already location-independent.
* **Monadic/dynamic rules** (Shake-style `need` discovered mid-recipe) and order-only deps.
* Persistent hash cache keyed by (inode, size, mtime) to skip re-hashing large trees; a daemon with inotify instead of polling in `watch`.
* Windows support (process groups, `flock`) and files with spaces in names.
* A `compile_commands.json` / Ninja-file exporter and a Makefile importer.

## Layout

```
cmd/mortise/        CLI, watch loop
internal/mf/        Mortisefile lexer/parser/expander, glob
internal/build/     rule resolution, scheduler, staleness engine, DB, CAS, depfile parser, explain/graph/report
examples/cproj/     real C project used by the demo
demo.sh             end-to-end verification
PLAN.md REVIEW.md   design and adversarial review
```
