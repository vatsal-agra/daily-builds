# Kestrel — Adversarial Review (Phase 3)

Method: attack the tracker as a hostile reviewer — brute-force oracles for the combinatorial core,
8-seed sweeps of every scenario × filter × association, pathological scenarios (pure clutter, no clutter,
bearing wrap at ±π, target next to the sensor, fast target leaving coverage), malformed input.
"Fresh run-through" = the same sweeps re-run after the fixes (numbers below are before → after).

## Findings

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| 1 | HIGH | **JPDA bred duplicate/coalesced false tracks.** Swarm, 8 seeds: 1 265 false-track scans, 215 distinct tracks (truth: 64). Detections that JPDA had softly explained were still unclaimed, so new tentative tracks were born from them. | `swarm ekf jpda ospa=531 false=1265` | JPDA now runs on *confirmed* tracks only; tentative tracks get hard GNN over the detections JPDA left unclaimed; detections gated by a confirmed track (β≥0.25) never seed births. → false 0, tracks 64, OSPA 104 (= GNN). |
| 2 | HIGH | **M-of-N confirmation alone confirms clutter.** UKF swarm: 216 false-track scans; pure-clutter run confirmed tracks continually. Tentative tracks have σv = 117 m/s so their gates are huge and 3 hits in 5 scans is cheap. | `swarm ukf gnn false=216`, `ukf cruise false=18` | Track **score** (cumulative log-likelihood ratio vs the clutter hypothesis, Blackman-style) must also exceed `ScoreConfirm`. Threshold chosen empirically: true tracks confirm at score ≥ 3.1 (median 11.7); false-track rate in 15 clutter/scan falls 27 → 8 per 2 000 scans at threshold 4 with *no* extra missed truth-scans. |
| 3 | MED | **Slow deletion.** A confirmed track coasted `MaxMiss+1 = 6` scans after its target vanished (birthdeath: 79 false-track scans; manoeuvre-CV: 179, because lost tracks lingered while replacements were born). | `birthdeath false=79` | Delete when score falls `DeleteDrop` (9) below its peak — 3 misses at Pd=0.95, ~7 at Pd=0.7, i.e. adaptive to detection probability. → birthdeath 47, manoeuvre 53. |
| 4 | MED | **UKF used α=0.5, κ=0**, giving a *negative* centre covariance weight (wc₀ = −0.25) and λ<0: legal but can yield a non-PSD covariance. | weights computed by hand | α=1: λ=0, all covariance weights ≥ 0. NEES/NIS consistency re-verified after the change (UKF radar: NEES 3.995, NIS 1.993 — inside 95% bounds). |
| 5 | MED | **Scoring penalised the tracker for targets the radar cannot see.** A fast target flying out of range was counted as "missed" for the rest of the run (OSPA 602). | `fast … ospa=602 miss=35` | `Truth.InCoverage` added; scorer ignores out-of-coverage truth. → OSPA 101, miss 2. |
| 6 | LOW | Pure-clutter and no-clutter configs: `ClutterMean=0` gave density 0 (log of 0 → NaN costs); `Pd=1` gave `log(1−Pd) = −Inf`. | code reading + probe | density floored at 1e-12, Pd clamped to 0.9999 in `ForScenario`; `Config.validate` rejects Pd∉(0,1) or density ≤ 0 for direct users. |
| 7 | LOW | `assoc.GNN` / `Hungarian` correctness unproven for forbidden cells and rectangular input. | — | 3 000 random rectangular matrices with 30% forbidden cells vs. exhaustive search: **0 mismatches**, infeasibility reported correctly (now a permanent test). |
| 8 | LOW | Malformed input: NaN detection, repeated/backwards scan time. | probe | Tracker returns descriptive errors (verified), no panic. Empty scans are fine. |
| 9 | LOW | Bearing wrap at ±π (target flying along the −x axis). | `wrap` scenario | Passes: no false tracks, 0 ID switches — innovations wrap, UKF means use wrapped residual averaging. |

## Known limitations (documented, not bugs)
* A CV-model EKF/UKF loses a target during a sustained 3°/s turn (model mismatch); that is exactly what the IMM exists to fix (manoeuvre OSPA 146 → 73).
* Track-deletion latency still shows up as a few "false-track scans" after a target dies or leaves coverage — a delete rule fast enough to remove that would also delete real tracks on dropouts.
* JPDA and GNN are indistinguishable on the stock scenarios (targets are mostly well separated) — a closely-spaced-targets scenario is needed to show a difference (added in Phase 4).
* JPDA is not combined with IMM (the soft update writes one Gaussian into the filter, which would collapse the mode bank); the tracker returns a clear error instead.
