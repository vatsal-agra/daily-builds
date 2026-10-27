# Bayou — PLAN

## Concept
Bayou is a from-scratch **Bayesian-network engine**: describe a probabilistic model in a small text
DSL (or the standard BIF format), then ask it questions — *"given a positive X-ray and a smoker,
how likely is cancer?"*, *"what is the single most likely explanation of these symptoms?"*,
*"are these two variables independent once I know a third?"* — or hand it data and have it
**learn** the parameters and even the graph. It is the reasoning-under-uncertainty toolkit
(think `pgmpy` / Hugin / Netica) in miniature, written in Go with the standard library only.

## Why it is interesting
* The repo has SAT, SMT, Datalog, Prolog, LP — all *logical/deterministic* reasoning. Nothing
  *probabilistic*. Bayou is the repo's first probabilistic-graphical-model build.
* One question, four different algorithms (enumeration, variable elimination, junction tree,
  sampling) that must agree — a perfect setting for differential testing against an oracle.
* Real graph theory (moralisation, triangulation, junction trees, d-separation) and real numerics
  (log-space, underflow, impossible evidence) in one coherent product.

## Architecture
```
cmd/bayou           CLI (query, map, marginals, dsep, sample, learn, structure, check, report, gen)
internal/bn         Network model, validation, topological order, forward sampling, joint prob
internal/factor     Factor algebra: product, marginalise (sum/max), reduce, normalise, argmax traces
internal/parse      .bn DSL parser + printer, BIF reader/writer, CSV/dataset reader
internal/graph      Moral graph, elimination orders (min-fill/min-weight), triangulation,
                    maximal cliques, junction-tree construction, d-separation (Bayes-ball)
internal/infer      Brute-force enumeration (oracle), variable elimination, MPE/MAP,
                    junction-tree (Hugin) calibration, likelihood weighting, Gibbs
internal/learn      MLE/Laplace, EM with missing values, BIC/K2 scores, hill-climb structure search
internal/report     Self-contained HTML report (graph layout, marginals, evidence what-if)
examples/           Real networks: asia, sprinkler, alarm-lite, student, car-diagnosis ...
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Model language + validation**: `.bn` DSL and BIF import/export, CPT checks (sums to 1, cycles, arity, unknown parents), round-trip printer, CSV data reader | **required** |
| 2 | **Exact inference by variable elimination**: posterior marginals under evidence, joint evidence probability P(e), MPE (most probable explanation) and MAP over a variable subset, min-fill ordering, impossible-evidence detection, brute-force oracle | **required** |
| 3 | **Junction tree + structural queries**: moralise → triangulate → max cliques → junction tree → Shafer–Shenoy calibration giving *all* marginals in one pass; d-separation (Bayes-ball), Markov blanket, independence listing | **required** |
| 4 | **Parameter learning**: forward sampling of datasets, MLE with Laplace smoothing, EM for missing values / latent variables (using the junction tree for E-step), log-likelihood tracking | **required** |
| 5 | **Approximate inference**: likelihood weighting and Gibbs sampling with convergence/error report vs. exact | stretch |
| 6 | **Structure learning**: hill-climbing over DAGs with BIC / K2 scoring, add/delete/reverse moves, recovery metrics (SHD) | stretch |
| 7 | **HTML report**: layered graph drawing, marginals bars, evidence what-if, light/dark | stretch |
| 8 | **Value of information / sensitivity**: which unobserved variable is most informative next (expected entropy reduction) | stretch |

## Definition of done
Differential tests (VE vs JT vs enumeration on hundreds of random nets, d-sep vs numeric
independence, EM likelihood monotone, learned params converge to truth, samplers within
tolerance), CLI demo script, adversarial REVIEW.md with every finding fixed, README + LEDGER.
