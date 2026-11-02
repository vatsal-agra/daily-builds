# Kestrel — a multi-target radar tracking laboratory

Kestrel simulates a radar watching several aircraft through clutter and missed detections, then *tracks* them
from scratch: how many targets are there, where is each one, and how sure are we? Everything is Go standard
library only (~3,600 lines + ~1,100 lines of tests): the matrix algebra, Kalman filters, optimal assignment,
chi-square functions, simulator, scorer and HTML report are all written here.

## Run it
```bash
cd 2026-11-02-kestrel
./verify.sh                                  # vet + unit tests + 32 end-to-end assertions
go build -o kestrel ./cmd/kestrel
./kestrel scenarios                          # cruise crossing swarm manoeuvre birthdeath dropouts knot
./kestrel run -scenario swarm -filter ukf -tracks
./kestrel run -scenario cruise -smooth       # RTS-smoothed accuracy
./kestrel compare -scenario manoeuvre        # every filter x association, averaged over seeds
./kestrel consistency -filter ekf -sensor radar   # Monte-Carlo NEES/NIS chi-square test
./kestrel consistency -filter kf -mismatch 0.005  # deliberately wrong noise model -> INCONSISTENT
./kestrel smooth                             # KF vs KF+RTS
./kestrel report -scenario knot -assoc jpda -smooth -o report.html   # self-contained SVG page (light/dark/phone)
```
Everything is seeded (`-seed`), so every number below is reproducible.

## Features
**Required (all shipped)**
1. **Kalman filter with statistical honesty tests** — CV/CA models, Joseph-form update, and Monte-Carlo NEES/NIS tests against exact chi-square acceptance bounds (own regularised-gamma + quantile code). An honest filter passes (NEES 4.02 vs expected 4, bounds [3.96, 4.04]); a filter given 100× too small process noise fails at NEES ≈ 80.
2. **EKF and UKF on nonlinear radar** — range/bearing measurements, angle-wrapped innovations (verified across the ±π cut), scaled unscented transform with circular-safe means. Both are consistent on radar data (NEES 3.99, NIS 1.99).
3. **Data association** — Mahalanobis gating at a chi-square quantile, Kuhn–Munkres Hungarian assignment (verified against brute force on 3,000 random matrices incl. forbidden cells), global-nearest-neighbour with likelihood-ratio costs that weigh Pd and clutter density so a track can prefer "missed" over a clutter-grade match.
4. **Track lifecycle, simulator, scoring, CLI** — tentative → confirmed (3-of-5 *and* a log-likelihood-ratio score) → coasting → deleted (score fell 9 below its peak), duplicate-track merging, OSPA / RMSE / ID-switch / false-track / coverage scoring, 7 built-in scenarios.

**Stretch (all shipped)**
5. **IMM** (CV + coordinated-turn, 5-state): halves error on manoeuvring targets (OSPA 178 → 110, RMSE 101 → 47 m).
6. **RTS smoother**: 71% lower RMSE in the Monte-Carlo test, and the smoothed covariance is still chi-square *consistent* (NEES 4.05); also works on live tracker tracks (`run -smooth`).
7. **JPDA** (exact joint-event enumeration per cluster, GNN fallback beyond 200k events): on the 250 m-spaced `knot` formation, 4 vs 15 UKF ID switches and RMSE 84 vs 110 m compared with GNN.
8. **HTML/SVG report**: plan view with truth, clutter, tracks, 95% uncertainty ellipses; OSPA-over-time chart; track table. Light/dark, checked in headless Chromium at phone width.

## Layout
`mat` linear algebra · `stat` RNG, chi-square · `model` CV/CA/CT + Cartesian/radar · `filter` KF/EKF/UKF/IMM · `assoc` Hungarian, gating, GNN · `tracker` lifecycle + JPDA + RTS recording · `sim` scenarios · `metrics` OSPA/consistency · `smooth` RTS · `lab` Monte-Carlo experiments · `report` HTML · `cmd/kestrel` CLI. See PLAN.md (design) and REVIEW.md (what the adversarial pass found and fixed).

## Why I chose this today
The repo has SAT/SMT, compilers, databases, a SLAM simulator… but nothing on *recursive Bayesian state estimation* proper, and nothing where "is it correct?" is answerable by a statistical test rather than an assertion. Multi-target tracking packs the whole stack (covariance propagation, nonlinear filtering, combinatorial assignment, lifecycle decisions) into a problem whose output is checkable against ground truth. The review found real bugs of the kind that only show up under statistics (JPDA breeding 215 tracks for 64 targets; M-of-N confirming clutter).

## Honest limitations
Radar is a single 2-D range/bearing sensor (no Doppler); clutter is uniform; JPDA isn't combined with IMM; the CT Jacobian's turn-rate column uses a central difference; deletion latency still shows as a few false-track scans after a target dies.

## Where a human could take this next
* Add Doppler (range-rate) measurements and a 3-D / elevation model; multi-sensor fusion with track-to-track association.
* Replace JPDA with MHT or a labelled RFS filter (GLMB / PMBM) and compare on `knot`.
* Particle-filter or Gaussian-sum backend; adaptive process noise (innovation-based Q estimation).
* Feed real recorded detections (ADS-B/radar CSV) through `tracker.Step`; the interface is just `(time, [range, bearing]...)`.
* Interactive viewer with a scan scrubber instead of a static report.
