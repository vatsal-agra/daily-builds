# Pinion — Plan

## Concept
**Pinion** is a package-dependency resolver built on the **PubGrub** algorithm (the
conflict-driven solver behind Dart's `pub`, Poetry's resolver and Cargo's `pubgrub-rs`),
written from scratch in Ruby with no gems. Give it a project manifest and a package
registry and it either returns one consistent set of versions, or — the whole point of
PubGrub — a **human-readable derivation** of *why no solution exists*:

```
Because app depends on web ^2.0.0 and web >=2.0.0 <2.3.0 depends on http ^1.0.0,
  app requires http ^1.0.0.
And because json 1.4.0 depends on http ^2.0.0 ...
```

## Why it is interesting
* Dependency resolution is NP-complete (it embeds SAT) — yet every developer hits it daily.
* Nobody in this repo has built the layer between "a SAT solver" and "a package manager".
  PubGrub is CDCL specialised to *version ranges*: clauses are "incompatibilities" over
  version sets, learned clauses double as the proof, and the proof is rewritten into prose.
* Every piece is a real algorithm: interval algebra over a dense total order, unit
  propagation over set-valued literals, 1-UIP-style conflict resolution with
  backjumping, and derivation-DAG pretty-printing with shared-lemma numbering.
* It can be verified hard: a brute-force oracle must agree on SAT/UNSAT for thousands of
  random registries, solutions are re-checked, and every leaf fact in an UNSAT
  explanation is checked against the registry.

## Architecture
```
 manifest.json ─┐                      ┌─> solution ──> pinion.lock (with integrity hashes)
 registry.json ─┼─> Universe ─> Solver ┤
 pinion.lock ───┘  (yank/pre policy)   └─> failure incompat ──> Reporter ──> prose
                                  ▲
        Version / VersionSet / Constraint   (interval algebra on positions)
        Term / Incompatibility / PartialSolution  (PubGrub state)
```
* `version.rb`      – SemVer 2.0 parse + total order (prerelease rules).
* `version_set.rb`  – union/intersect/complement/subset over position-based intervals.
* `constraint.rb`   – `^ ~ ~> >= <= != x-ranges, hyphen ranges, ||, comma/space AND`.
* `term.rb`, `incompatibility.rb`, `partial_solution.rb` – PubGrub data model.
* `solver.rb`       – unit propagation, conflict resolution/backjumping, decisions.
* `report.rb`       – derivation DAG → numbered prose.
* `registry.rb`, `manifest.rb`, `lockfile.rb` – I/O, universe filtering, integrity.
* `oracle.rb`, `gen.rb` – brute-force checker and random-registry generator.
* `cli.rb`          – `pinion resolve|lock|verify|tree|why|update|diff|graph|fuzz|gen`.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | SemVer + constraint language + exact VersionSet algebra | **required** |
| 2 | PubGrub solver: propagation, conflict learning, backjumping, newest/oldest/locked strategies | **required** |
| 3 | Human-readable failure explanations from the derivation DAG | **required** |
| 4 | Manifest/registry/lockfile I/O with integrity hashes + CLI (`resolve lock verify tree why`) | **required** |
| 5 | Differential fuzzer vs brute-force oracle, incl. explanation-leaf verification | stretch |
| 6 | Conservative `update` (change as little of the lock as possible) + lock `diff` | stretch |
| 7 | Self-contained HTML dependency-graph report | stretch |
| 8 | Prerelease & yank policy (opt-in prereleases, yanked kept only if locked) | stretch |

## Definition of done
All gates in the task: features 1-4 end-to-end, REVIEW.md with fixes, ≥1 stretch,
tests green (`./verify.sh`), README + LEDGER entry.
