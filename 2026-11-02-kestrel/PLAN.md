# Kestrel — Plan

## Concept
Kestrel is a from-scratch **multi-target radar tracking laboratory** in Go (stdlib only). A simulator
flies several targets (straight, accelerating, turning, crossing, diverging) past a radar that reports
noisy range/bearing detections with missed detections and uniform clutter. Kestrel's tracker must
recover *how many* targets exist and *where* each one is, with honest uncertainty, using the classic
estimation stack: Kalman filter family -> gating -> optimal assignment -> track lifecycle -> scoring.

## Why it is interesting
Everything else in this repo is deterministic or logical. Beacon (SLAM) used a particle filter for one
robot; nothing covers *recursive Bayesian state estimation* proper: covariance propagation, nonlinear
measurement linearisation, the unscented transform, and — hardest — the data-association problem when
you don't know which detection belongs to which target. The results are checkable against ground
truth with statistical tests (NEES/NIS chi-square consistency, OSPA), so "works" is measurable, not vibes.

## Architecture
```
mat/      dense matrices: LU inverse/solve/det, Cholesky, symmetrise (no deps)
stat/     seeded Gaussian sampling (via Cholesky), chi-square CDF/quantile (regularised gamma)
model/    motion models (CV, CA, CT w/ turn rate) + measurement models (Cartesian, radar range/bearing)
filter/   KF, EKF, UKF behind one Filter interface; IMM mixing filter
assoc/    Mahalanobis gating, Hungarian (Kuhn–Munkres, rectangular), GNN, JPDA (stretch)
tracker/  track lifecycle (tentative -> confirmed -> coasting -> deleted, M-of-N), multi-target loop
sim/      scenarios, truth trajectories, radar with Pd / clutter / noise
metrics/  RMSE, NEES, NIS with chi-square bounds, OSPA, track-to-truth scoring
cmd/kestrel  CLI: scenarios, run, consistency, compare, report (HTML/SVG)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Linear Kalman filter (CV/CA models, Joseph-form update) with NEES/NIS consistency testing against chi-square bounds | **required** |
| 2 | EKF and UKF for nonlinear radar (range/bearing) measurements, angle-wrapped innovations; head-to-head comparison | **required** |
| 3 | Data association: chi-square gating + Hungarian optimal assignment (GNN) under clutter and missed detections | **required** |
| 4 | Track lifecycle manager (M-of-N confirmation, coasting, deletion) + scenario simulator + OSPA/RMSE scoring, end-to-end CLI | **required** |
| 5 | IMM filter (CV + coordinated-turn mixing) for manoeuvring targets | stretch |
| 6 | Rauch–Tung–Striebel smoother (offline refinement) | stretch |
| 7 | JPDA association alternative for dense clutter / crossing targets | stretch |
| 8 | Self-contained HTML/SVG report: truth vs tracks, OSPA over time | stretch |

## Done means
All 4 required fully working; adversarial REVIEW.md with fixes; at least one stretch (aim for all);
`verify.sh` runs unit tests + end-to-end demo green.
