# Bellman

**Status: Phase 2 complete — all 4 required features implemented and
verified end to end.** Adversarial review, stretch features, and final
polish are still ahead.

A from-scratch reinforcement learning laboratory in pure Python (no
numpy, no gym, no RL/ML framework). See [PLAN.md](PLAN.md) for the full
concept, architecture, and feature list.

## What's working right now

- `bellman/envs/cliffwalking.py` + `bellman/dp.py` — the classic 4x12
  Cliff Walking MDP solved exactly by Policy Iteration and Value
  Iteration (both agree: optimal value at the start state is -13).
- `bellman/td.py` — tabular SARSA and Q-learning. Reproduces the textbook
  Sutton & Barto result: Q-learning's greedy policy hugs the cliff edge
  (value -13, matches DP optimum exactly), SARSA's takes the longer safe
  route (value -17). A SARSA(λ) variant (replacing eligibility traces) is
  also implemented and demonstrably reaches a working policy in far fewer
  episodes than 1-step SARSA at matched hyperparameters.
- `bellman/envs/tictactoe.py` + `bellman/minimax.py` — a memoized negamax
  solver that plays provably optimal Tic-Tac-Toe (5478 reachable states,
  200/200 draws when it plays itself).
- `bellman/selfplay.py` — a TD(0) self-play value-learning agent (no
  minimax knowledge injected) that, after training, beats the perfect
  oracle 0 times and draws every remaining game across 300 randomized
  games as both X and O.
- `bellman/viz_export.py` — runs everything above and exports the results
  (values, policies, trajectories, training curves, the full learned
  value table and the full solved game tree) to
  `visualizer/data/bellman_data.js`.
- `visualizer/index.html` — a self-contained interactive dashboard: value
  heatmaps with policy arrows and a trajectory scrubber/playback for
  every Cliff Walking algorithm, training curves, a SARSA vs SARSA(λ)
  convergence-speed chart, and a live Tic-Tac-Toe board you can play
  against either the self-play agent or the perfect oracle (entirely
  client-side, no server needed once the data is generated). Verified
  with a headless-Chromium run: zero console errors, correct oracle
  counter-play, correct win/loss/draw detection.

## Run it yourself

```
python3 -m bellman.viz_export           # regenerates visualizer/data/*
python3 -m http.server 8000             # from the visualizer/ directory
# open http://localhost:8000
```

(Opening `index.html` directly by double-clicking also works — the data
is inlined as a plain `.js` file specifically so there's no `fetch()` of
local JSON to trip over `file://` CORS restrictions.)
