# Bayou

**A from-scratch Bayesian-network engine in Go — standard library only.** Describe a probabilistic
model in a small text language (or load a standard BIF file), then ask it questions, hand it data
and have it learn the parameters *and the graph*, or open it as an interactive page.

```
$ bayou query examples/burglar.bn -q Burglary -e Alarm=yes
P(Burglary | Alarm=yes)    [P(evidence) = 0.0025164]
  yes   0.373551  ███████████
  no    0.626449  ██████████████████

$ bayou query examples/burglar.bn -q Burglary -e Alarm=yes,Earthquake=yes     # explaining away
  yes   0.003 …
```

It is the toolkit behind Hugin / Netica / `pgmpy` in miniature: exact inference three different
ways that must agree, sampling for networks too big for exact methods, parameter learning with
missing and latent data, structure learning, value-of-information analysis and an in-browser
explorer — about 6,300 lines of Go, 2,800 lines of tests, and a 200-line JavaScript engine.

## Run it

Requires Go ≥ 1.24 (no dependencies). Node + Playwright are optional (browser check only).

```bash
go build -o bayou ./cmd/bayou
./bayou help

./bayou info      examples/asia.bn                                   # variables, edges, treewidth
./bayou query     examples/asia.bn -q Tuberculosis,LungCancer -e XRay=abnormal,Smoking=yes
./bayou marginals examples/asia.bn -e Dyspnea=yes                    # every marginal, one pass
./bayou mpe       examples/asia.bn -e Dyspnea=yes,XRay=abnormal      # most probable explanation
./bayou map       examples/burglar.bn -q Burglary,Earthquake -e Alarm=yes
./bayou dsep      examples/asia.bn -x Tuberculosis -y LungCancer -z Either
./bayou tree      examples/asia.bn                                   # the junction tree
./bayou sample    examples/student.bn -n 20000 -o data.csv
./bayou learn     examples/student.bn data.csv --truth examples/student.bn -o learned.bn
./bayou structure examples/car.bn car.csv --score bic --truth examples/car.bn
./bayou approx    examples/student.bn -q Intelligence -e Letter=strong --method gibbs
./bayou voi       examples/car.bn -q BatteryDead -e Starts=no --cost Radio=0.1 --detail
./bayou report    examples/asia.bn -o asia.html                      # open in a browser

./verify.sh        # gofmt, vet, 88 Go tests, CLI demo, headless-browser check, mutation run
./demo.sh          # the 8-step guided tour with assertions
```

Evidence is `NAME=state,NAME=state`; every inference command also takes `--json`.
Example networks in `examples/`: `asia` (chest clinic), `student`, `sprinkler`, `burglar`,
`car` (diagnostic), `weather-hmm` (an unrolled hidden Markov model with latent weather).

### The `.bn` language
```
network "Asia"
var Smoking { yes, no }
var LungCancer { yes, no }
var Either { yes, no }
cpt Smoking = 0.5, 0.5
cpt LungCancer | Smoking {
    yes: 0.10, 0.90
    no:  0.01, 0.99
}
cpt Either | Tuberculosis, LungCancer {      # '*' matches any state; explicit rows win
    no, no: 0, 1
    *,  *:  1, 0
}
```
Commas are optional, fractions (`1/3`) work, errors carry `file:line:col`, and `bayou convert`
translates to and from BIF losslessly.

## Features (all shipped)

**Required**
1. **Model language + validation** — `.bn` DSL and BIF import/export, CPT/cycle/arity checks reporting every problem, bit-exact round-trip printer, CSV reader with missing cells, wildcards, "did you mean" suggestions.
2. **Exact inference by variable elimination** — posteriors, joint posteriors, P(evidence) in log space (a 400-variable chain with P(e) ≈ 10⁻⁸⁰⁰ is exact), MPE and marginal MAP with traceback, barren-node pruning, min-fill planning that refuses hopeless plans *before* allocating, a brute-force enumeration oracle.
3. **Junction tree + structural queries** — moralise → triangulate → maximal cliques → max-weight spanning tree → Shafer–Shenoy calibration (all marginals, family marginals and log P(e) in two passes), d-separation by Bayes-ball, Markov blankets, full independence listing.
4. **Parameter learning** — forward sampling with missing cells / hidden variables, Laplace-smoothed MLE, EM for missing and latent data (junction-tree E-step, monotone log-likelihood, random restarts), exact chain-rule KL to a reference model.

**Stretch**
5. **Approximate inference** — likelihood weighting (ESS, P(e) estimate) and multi-chain Gibbs (batch-means ESS, split-chain R̂ that flags stuck chains); answers on networks whose treewidth makes exact inference impossible.
6. **Structure learning** — tabu search over add/delete/reverse moves with BIC, K2 and BDeu, max-parents, restarts, and equivalence-class-aware SHD against a reference graph (CPDAG construction with Meek rules).
7. **Interactive HTML report** — one file, no external resources, light/dark/phone: layered graph, live posterior bars with prior ticks, click-to-observe, impossible-evidence rollback, CPT inspector, d-separation dimming, shareable `#e=` URL, powered by a JavaScript port of the exact engine that is tested against the Go one.
8. **Value of information** — rank unobserved variables by expected entropy reduction (= mutual information), with per-test costs and what each outcome would tell you.

## How it's built
```
cmd/bayou          CLI (18 commands)
internal/bn        network model, validation, sampling, random-network generator
internal/factor    factor algebra with log-scaling (no underflow) and size guard
internal/parse     .bn parser/printer, BIF reader/writer, CSV
internal/graph     moralisation, min-fill planning, junction tree, d-separation
internal/infer     enumeration, VE, MAP/MPE, junction tree, LW, Gibbs, VOI
internal/learn     MLE, EM, KL, tabu structure search, CPDAG/SHD
internal/report    layout, HTML template, engine.js (browser inference)
tests/             headless-browser check, mutation suite
```

## How it was verified
* **Differential testing**: enumeration vs VE vs junction tree on 400 random networks (with exact zeros, impossible evidence, disconnected graphs): posteriors, joint posteriors, family marginals and log P(e) agree to 1e-9; MAP optimum matches brute force on 300 problems.
* **d-separation vs numbers**: separated ⇒ exactly independent, connected ⇒ dependent, on 120 random triples; CPDAG vs brute-force enumeration of every DAG in its equivalence class.
* **Learning**: recovered parameters within 2·10⁻⁴ nats KL; EM likelihood monotone; EM on complete data equals MLE; all four reference networks recovered exactly by structure search.
* **Browser engine = Go engine** on 192 random evidence sets; the real page is driven by Playwright (mouse + keyboard, three viewports, console clean).
* **Mutation testing**: 18 injected bugs, all killed by the suite (2 equivalent mutants documented).
* **Two written adversarial reviews** (`REVIEW.md`): 20 findings fixed — including silent CSV data corruption, an OOM on high-treewidth networks, an O(n³) planner and a greedy structure search that returned graphs worse than the truth.

Performance (laptop-class VM): 5,000-variable sparse network, all marginals under evidence — 0.75 s; query on a 1,500-variable chain — 0.1 s; 60-variable report recomputes all marginals on each click in ~40 ms.

## Why I built this today
This repo already has SAT, SMT, Datalog, Prolog, LP and type-inference engines — all *logical*
reasoning. Nothing handled **uncertainty**. A Bayesian network is also an unusually good thing to
build test-first: there are several algorithms that must give the same number, plus a brute-force
oracle, so correctness can be checked mechanically rather than eyeballed — and the project spans
graph theory (triangulation, junction trees, d-separation), numerics (underflow, zeros),
statistics (EM, scores) and UI in a coherent product.

## Known limits
* Exact inference stops at 2²⁵ entries per table (reported as an error that points to `approx`); the report at 2²⁰ / 120 variables.
* Gibbs cannot cross hard deterministic constraints; R̂ flags it. Structure search is heuristic (no optimality guarantee; BIC on Asia needs ~200k rows).
* Discrete variables only; no continuous / noisy-OR / decision nodes; EM's random start also randomises deterministic CPTs.
* BIF `table` for a child *with* parents uses Bayou's layout (parents slowest); the per-row form Bayou writes is unambiguous.

## Where a human could take this next
* **Continuous and hybrid variables** (conditional Gaussians) and canonical CPD families (noisy-OR/MAX, decision trees) so big diagnostic nets need exponentially fewer parameters.
* **Better search and sampling**: greedy equivalence search (GES) or exact DP structure learning for ≤ 25 variables; blocked/collapsed Gibbs and loopy belief propagation; cutset conditioning to bridge exact and approximate methods.
* **Decision networks** (utilities, expected-utility value of information) and dynamic networks with an online filter for time series — the unrolled HMM here is the seed.
* **Parameter priors & learning from interventions** (do-calculus, causal effect estimation on the learned graph).
* A web service around `engine.js` so the report can load networks from files, edit CPTs and share sessions.
