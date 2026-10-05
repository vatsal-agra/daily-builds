# Kepler

**A symbolic-regression engine in Go (stdlib only): give it numbers, get back the *equation*.**

Feed it a CSV and it searches the space of mathematical formulas — genetic programming over
expression trees, Nelder-Mead tuning of the constants inside each tree, a Pareto front of
accuracy-vs-simplicity, and held-out validation to pick the model that generalises. Out comes
something a human can read, like `T = 6.28319 * sqrt(L) / g^0.5` or `F = 6.674 * m1 * m2 / r^2`,
not a black box. It is named for Kepler, who famously extracted his laws from Tycho Brahe's tables;
the benchmark suite asks Kepler-the-program to do the same.

```
$ ./kepler gen kinetic > k.csv && ./kepler fit -q k.csv
Pareto front for E  (120 rows, 5 gens, 237797 evals, 998ms)
     cplx   train NMSE      holdout  formula
        1    1.010e+00    1.010e+00  E = 117.025
        4    5.581e-01    5.721e-01  E = 20.8942 * v
        7    1.159e-01    9.199e-02  E = 4.51206 * m * v
        8    7.677e-03    6.096e-03  E = v^1.69792 * m
*      10    1.839e-15    1.505e-15  E = 0.5 * m * v^2
```

## Run it

```bash
go build -o kepler ./cmd/kepler        # Go >= 1.21, no dependencies
./kepler bench                         # rediscover 7 physics laws from sampled data
./kepler bench -report bench.html      # ...and write a self-contained HTML report
./kepler fit mydata.csv                # last column = target; or  -target colname
./kepler fit -time 30s -report r.html mydata.csv
./kepler eval "2*pi*sqrt(L/g)" L=1 g=9.81
./kepler diff "x^2*sin(x)" x           # symbolic derivative
./kepler datasets                      # list built-in benchmarks
go test ./...                          # ~75 tests (add -short to skip the slow search tests)
./demo.sh                              # guided tour of every feature; exits non-zero on failure
```

CSV format: header row, numeric cells, column names that are plain identifiers (`mass`, `v0`).
Bad input produces a line-numbered error rather than silent skipping. `#` comment lines, blank lines,
CRLF and Excel's UTF-8 BOM are handled.

Flags for `fit`/`bench`: `-pop -gens -islands -seed -maxsize -holdout -ops "+,-,*,/,^,sqrt,exp,log,sin,cos,abs,neg"
-time 30s -report out.html -q -target col`. Same seed + same flags ⇒ byte-identical result.
Ctrl-C ends the search gracefully and prints the front found so far.

## Features

**Required (core)**
1. **Expression engine** — AST with protected evaluation (division by zero, log/sqrt of negatives, overflow → "undefined", never crashes), an infix parser with positioned error messages (`**` accepted), a minimal-parenthesis printer, and an algebraic simplifier: constant folding, identities, like-term collection (`x^3 - x - x → x^3 - 2*x`), monomial normalisation (`m2/r/(c/m1)/r → m1*m2/(r^2*c)`). Property-tested: simplification never changes a function's value.
2. **Genetic-programming search** — ramped half-and-half init, tournament selection, subtree crossover, subtree/point/hoist/constant mutations, elitism, size & depth caps against bloat, parsimony pressure, seeded determinism.
3. **Constant optimisation** — every candidate with promising structure has all its numeric leaves tuned by Nelder-Mead (`opt/`), with restarts in the final polish. Evolution searches *structure*; optimisation finds the *numbers*.
4. **Pareto front + CLI** — the archive keeps the best formula per complexity; the final front is polished on the full training set, pruned of vestigial terms (`+ 4.6e-07`), and constants are snapped to readable values (`1.50003 → 1.5`, `0.4999 → 0.5`). `fit` for your own CSV, `bench` for built-in laws with ground truth.

**Stretch (all four shipped)**
5. **Island model** — parallel populations on goroutines with ring migration; deterministic because islands synchronise every generation.
6. **Holdout validation + knee selection** — models are scored on unseen rows; the recommended `*` model minimises `error·exp(0.06·complexity)`, so extra terms must buy real accuracy (this is what stops it fitting 1 % noise with a 31-node monster).
7. **Symbolic differentiation** — `kepler diff` (sum/product/quotient/power/chain rules incl. `x^x`), verified against finite differences.
8. **HTML report** — dark/light, self-contained SVG Pareto plot, fit plot (curve for 1-D, predicted-vs-actual otherwise), full model table.

## Benchmarks (generated from the true law; 120 rows; seed 1)

| law | truth | found |
|---|---|---|
| Kepler's 3rd | `T = a^1.5` | `T = a^1.5` |
| pendulum | `2π·sqrt(L/g)` | `6.28319 * sqrt(L) / g^0.5` |
| kinetic energy | `0.5·m·v²` | `0.5 * m * v^2` |
| gravitation | `6.674·m1·m2/r²` | `6.674 * m1 * m2 / r^2` |
| ideal gas | `8.314·n·T/V` | `8.314 * n * T / V` |
| radioactive decay, 1 % noise | `100·e^(-0.3t)` | `99.914 / 1.34941^t` (= 99.9·e^(-0.2998t)) |
| damped wave | `5·e^(-0.2t)·cos 2t` | `cos(2t) · 1.2214^(8.047 - t)` (= 5.0·e^(-0.2t)·cos 2t) |

"Rediscovered" is judged on 300 fresh *noiseless* points (NMSE < 1e-3), not on the training data.

## Layout
```
expr/    AST, eval, parser, printer, simplifier, derivative
opt/     Nelder-Mead
data/    CSV I/O, split, benchmark laws + generators
gp/      fitness (NMSE), constant fitting/snap/prune, operators, islands, archive, selection
report/  HTML+SVG reports
cmd/kepler  CLI           PLAN.md · REVIEW.md · demo.sh
```

## Why I chose this today
The ledger is full of "build X from scratch" systems — compilers, databases, solvers, renderers — but nothing that
*discovers* something. Symbolic regression is the rare problem that fuses three classic ideas (evolutionary
search, numerical optimisation, multi-objective trade-offs) into one tool whose output is genuinely
informative, and it is verifiable: the benchmark laws have known answers. Seeing `a^1.5` fall out of a table of
planet data is a satisfying demo.

## Where a human could take this next
- **Dimensional analysis**: attach units to columns and forbid `metres + seconds` — prunes the search space enormously and guarantees physically meaningful laws (AI Feynman does this).
- **Equivalence-aware canonicalisation** (e-graphs / term rewriting) so `99.9/1.349^t` is shown as `99.9·exp(-0.2998 t)`; recognise `4.6043 = ln 100`.
- **Better search**: lexicase selection, semantic crossover, or neural-guided proposals; auto-restart across seeds and merge fronts.
- **More operators** (`tanh`, `atan`, integer powers, piecewise), and **vector/time-series** inputs with derivative features for discovering ODEs (SINDy-style).
- **Uncertainty**: bootstrap the constants to give error bars; report the confidence that structure A beats B.
- **A web UI** that streams the front live while evolution runs.
