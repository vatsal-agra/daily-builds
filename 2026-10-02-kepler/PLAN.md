# Kepler — Plan

## Concept
**Kepler is a symbolic-regression engine**: give it a table of numbers, it searches the space of
*mathematical formulas* and hands back equations like `T = 2*pi*sqrt(L/g)` — not a black-box
model but a human-readable law, along with the whole accuracy-vs-simplicity trade-off curve.
It is named for Kepler's rediscovery of planetary laws from Tycho's tables; the benchmark suite
literally asks it to rediscover Kepler's third law from noisy orbit data.

## Why it's interesting
Every neural net fits numbers; symbolic regression fits *knowledge*. It is genetic programming
(trees as genomes), continuous optimisation (constants inside the trees), and multi-objective
search (Pareto front of error vs. complexity) in one system. The repo has SAT, SQL, CRDTs,
type inference, creature evolution — but no tool that discovers equations from data.

## Architecture (Go, stdlib only)
```
expr/    AST (const, var, unary, binary), protected evaluation, parser, printer,
         simplifier (constant folding + algebraic identities), derivative, complexity
data/    CSV loader, deterministic noisy generators for physics benchmark laws
opt/     Nelder-Mead constant optimiser (fits all constants in a tree)
gp/      evolution: ramped half-and-half init, tournament selection, subtree crossover,
         subtree / point / hoist / constant mutations, bloat control, island model
         (goroutines + ring migration), Pareto-front hall of fame
report/  self-contained HTML report with SVG Pareto plot + fit plot
cmd/kepler  CLI: fit | bench | eval | diff | datasets
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Expression engine: AST, protected eval, parser, printer, algebraic simplifier | **required** |
| 2 | Genetic-programming search: init, tournament, crossover, 3 mutation kinds, bloat control, seeded determinism | **required** |
| 3 | Constant optimisation: Nelder-Mead tuning of all numeric leaves per candidate (+ restarts) | **required** |
| 4 | Pareto front (error vs complexity) hall-of-fame + CSV-driven `fit` CLI + built-in physics benchmark `bench` | **required** |
| 5 | Island model: parallel populations with ring migration (goroutines) | stretch |
| 6 | Holdout validation & knee-point model selection (picks the model that generalises) | stretch |
| 7 | Symbolic differentiation (`kepler diff`) of discovered/entered formulas | stretch |
| 8 | Self-contained HTML report with SVG Pareto + fit plots | stretch |
