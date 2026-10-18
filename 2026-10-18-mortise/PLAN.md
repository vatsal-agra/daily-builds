# Mortise — PLAN

## Concept
Mortise is a from-scratch **incremental build system** (think Make × Shake × Bazel's cache) in Go.
You describe a project in a `Mortisefile`; Mortise builds the minimum necessary, in parallel,
and can prove *why* anything was rebuilt.

## Why it's interesting
Make's mtime model is wrong in well-known ways (touch ⇒ rebuild, clock skew, restored files,
no command-change detection). Modern systems (Shake, Ninja, Bazel) fix this with **content hashes**,
**early cutoff** (a rebuilt-but-identical output does not invalidate dependents),
**dynamic dependencies** (discovered while the command runs, e.g. `gcc -MMD`), and
**content-addressed caches**. Building that machinery end-to-end — language, scheduler, persistent
database, cache — is a compact but deep systems problem not yet in this repo's ledger.

## Architecture
```
Mortisefile ──► internal/mf   lexer/parser/expander (vars, functions, pattern rules, globs)
                   │ Rules
                   ▼
              internal/build  Graph resolution (explicit + %-pattern rules, cycle detection)
                   │          Scheduler (goroutine per node, -j worker semaphore, -k keep-going)
                   │          Staleness engine (action key = cmd + input content hashes + dyn deps)
                   │          Depfile parser (make-style .d) → dynamic deps persisted in DB
                   ▼
              .mortise/db.json   (atomic, versioned)   .mortise/cas/   (content-addressed outputs)
cmd/mortise   CLI: build, -j, -k, -n, why, graph, clean, watch, stats
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Mortisefile language: variables, `$(glob/patsubst/subst/...)`, `%` pattern rules, automatic vars `$@ $< $^ $*`, phony targets, positioned parse errors | **required** |
| 2 | Parallel dependency scheduler: `-j N`, cycle detection with the full cycle path, `-k` keep-going, failed outputs removed, clear error reporting | **required** |
| 3 | Content-hash incremental builds with **early cutoff**; command changes, missing/tampered outputs, and deleted inputs all detected; persistent atomic DB | **required** |
| 4 | **Dynamic dependencies** from make-style depfiles (`@depfile`): recorded after the run, re-verified (and generated ones built first) on later runs | **required** |
| 5 | Content-addressed **action cache**: identical action (cmd + input hashes) restores outputs from `.mortise/cas` without running, even after `clean` | stretch |
| 6 | `why <target>` explainer (exact reason a target would rebuild), `graph` (DOT) and `-n` dry-run | stretch |
| 7 | `watch` mode (polling, debounce) and `stats` (build timeline: ran/cached/up-to-date/cutoff counts, critical path) | stretch |

Required: 1–4. Stretch: 5–7 (aim to ship all).

## Verification plan
Go unit tests per package, an integration test suite driving real shell commands, and `demo.sh`
that builds a real multi-file C project with gcc, edits headers/comments/generators, and asserts
rebuild counts (including early cutoff and header-via-depfile rebuilds).
