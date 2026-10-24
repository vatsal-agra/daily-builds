# Pinion

**A package-dependency resolver built on PubGrub — and the part everyone skips: it explains, in plain English, why no solution exists.**

Pure Ruby 3, standard library only (~2,300 lines + ~1,300 lines of tests).

```
$ pinion resolve conflict.json
error: no set of versions satisfies shopfront

Because webkit >=3.0.0 depends on tlslib ^3.0.0 and authlib <5.0.0 depends on tlslib ^2.0.0,
  webkit >=3.0.0 is incompatible with authlib <5.0.0.
And because shopfront depends on webkit ^3.0.0, authlib <5.0.0 is forbidden.
And because shopfront depends on authlib ^4.0.0, version solving failed.
```

## What it is

Dependency resolution is NP-complete — it embeds SAT — and every package manager has to do it.
Pinion implements the **PubGrub** algorithm (Dart `pub`, Poetry, Cargo's `pubgrub`): conflict-driven
clause learning where the literals are *sets of versions*, not booleans. Learned clauses ("incompatibilities")
double as the proof of failure, and Pinion rewrites that proof into numbered, human-readable prose.

Around the solver sits a small but complete package-manager toolchain: manifests, a registry format,
lockfiles with integrity checksums, conservative updates, and an HTML dependency-graph report.

## Run it

```bash
cd 2026-10-24-pinion
bin/pinion help
./demo.sh          # 11-step guided tour on examples/webapp (works on a temp copy)
./verify.sh        # 155 tests + differential fuzz + demo + headless-browser check
ruby -Itest test/all.rb   # just the tests
```

Needs Ruby ≥ 3.1. No gems. (`verify.sh` also runs a headless-Chromium check if Node + Playwright are present.)

Project files (all JSON):

```jsonc
// pinion.json                          // registry.json
{ "name": "shopfront",                  { "packages": {
  "dependencies": {                       "webkit": {
    "webkit": "^2.0",                       "2.4.0": { "dependencies": { "httpcore": "^1.2" } },
    "ormlite": "^1.0" },                    "1.0.0": { "dependencies": {}, "yanked": true } } } }
  "allow_prerelease": ["jsonkit"] }
```

| Command | What it does |
|---|---|
| `resolve [MANIFEST]` | Solve and print versions (`--strategy newest\|oldest`, `--json`, `--stats`, `--fresh` to ignore the lock) |
| `lock` | Solve, keeping the existing lock wherever constraints allow, and write `pinion.lock` (prints a diff) |
| `verify` | Re-check a lockfile against manifest + registry *without solving*: edits, tampering, removed versions, orphans; warns about yanked pins |
| `update [PKG…]` | Re-lock changing as little as possible: only the named packages move (none named = everything) |
| `tree` / `why PKG` | Dependency tree; every path to a package, the constraints on it, and exactly which dependent holds back each newer version |
| `diff A.lock B.lock` | Added / removed / upgraded / downgraded |
| `graph -o FILE` | Self-contained HTML graph (light/dark, click to trace, filter, "held back" badges) |
| `range CONSTRAINT [VERSION…]` | Parse a constraint, show its normal form, test versions against it |
| `gen` / `fuzz` | Random registries / differential-test the solver against a brute-force oracle |

Exit codes: `0` ok, `1` unsolvable / lock invalid / fuzz disagreement, `2` bad input or usage, `70` internal error.

## Features

**Core (required)**
1. **SemVer + constraint language + exact version-set algebra.** SemVer 2.0 ordering (prereleases, numeric/alphanumeric identifiers); `^ ~ ~> >= > <= < != = x-ranges * 1.2.3 - 2.0 ||` and comma/space AND. Sets are canonical interval lists over *positions* on the version line (just-before/just-after a version), so union / intersection / complement / subset are exact with no inclusive/exclusive special-casing — property-tested against pointwise membership.
2. **PubGrub solver.** Unit propagation over set-valued terms, conflict resolution with backjumping, learned incompatibilities, decision heuristic (fewest candidates first), `newest`/`oldest` strategies, lock preference, dependency-range widening (60 patch releases with the same dependency become one fact).
3. **Failure explanations.** The learned-clause DAG is walked iteratively into prose with shared lemmas numbered `(1)`, `(2)`…; understands "does not exist (did you mean…?)", "matching versions are hidden: yanked / prerelease", self-dependencies, and proofs 12,000 steps deep.
4. **Manifest / registry / lockfile + CLI.** Validated JSON inputs with located error messages; lockfile with per-package SHA-256 integrity and manifest fingerprint.

**Stretch (shipped)**
5. **Differential fuzzer** (`pinion fuzz`): thousands of random registries, solver vs. a deliberately naive backtracking oracle that shares no logic with it; solutions re-validated independently; **every learned clause and proof step is proven entailed by the registry**; every leaf of every failure proof is checked against the registry; the lock round-trip property is checked. The fuzzer is itself mutation-tested (4 planted solver bugs must each be caught).
6. **Conservative `update` + lock `diff`.**
7. **HTML dependency-graph report** (layered layout computed server-side; verified in headless Chromium in light, dark, and phone width).
8. **Prerelease & yank policy.** Prereleases hidden unless opted in (manifest list, `true`, or a range that names one); stable always beats a higher prerelease; yanked versions are never chosen fresh but stay installable when already locked (with a `verify` warning).

## Why I built this today

The repo has a CDCL SAT solver, a Prolog, an SMT solver, DNS, TLS, a Game Boy — but nothing that is a *package manager*, the most-used constraint solver in daily life, and nothing in Ruby. PubGrub is the rare algorithm whose novelty is half in the search (CDCL specialised to version ranges) and half in the UX (turning the proof into an error message a human can act on). It is also unusually verifiable: a brute-force oracle exists, so "does it agree on thousands of random universes, and is every learned clause actually true?" is a testable claim rather than a hope.

## Design notes & honest limits

* `lib/pinion/` — `version`, `version_set`, `constraint` (semantics) · `term`, `incompatibility`, `partial_solution`, `solver` (PubGrub) · `report` (proof → prose) · `registry`, `manifest`, `lockfile`, `resolver`, `depgraph`, `htmlreport`, `cli` · `oracle`, `gen`, `fuzz` (verification).
* Display folds the internal "before any prerelease" bound (`2.0.0-0`) to `2.0.0`; this only matters for prerelease versions, which are policy-hidden anyway.
* Backjumping rebuilds the trail, so pathological 10k-package chains take tens of seconds; real-sized graphs resolve in milliseconds (1,500-package chain: 0.4 s).
* No network: registries are JSON files. There is no download/install/build step.
* The `""` constraint means "any version".
* 16 review findings (incl. a solver hang, an XSS in the HTML report and a wrong caret display) are in [REVIEW.md](REVIEW.md); design in [PLAN.md](PLAN.md).

## Where a human could take this next

* **Real registries**: importers for `Gemfile.lock`/`package-lock.json`/crates.io index snapshots, to benchmark against Bundler's and Cargo's resolvers on real graphs.
* **Optional features & platform markers** (Cargo features, Python extras/environment markers) — these turn PubGrub into a harder, more interesting problem.
* **Multiple versions of one package** (npm-style duplicates when majors differ) via per-major package identity.
* **Better explanations**: collapse the "if X then Y or Z" 3-term incompatibilities, suggest concrete fixes ("relax `authlib` to `^5`"), and rank culprits by how many conflicts they appear in.
* **Incremental solving / daemon mode** for editors; persistent learned clauses across edits.
* **Speed**: avoid O(trail) backtracking with a persistent partial solution; index incompatibilities by watched terms.
