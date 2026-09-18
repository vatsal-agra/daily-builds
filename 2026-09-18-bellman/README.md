# Bellman

**Status: Phase 4 complete — stretch feature (REINFORCE on CartPole)
shipped and verified, plus a round of UX/input-validation polish.**
Final verification (tests + demo script) is next.

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

## Adversarial review

[REVIEW.md](REVIEW.md) has the full writeup. The two real bugs it found
and fixed: the documented `python -m bellman.viz_export` one-liner
crashed on a stale default (a self-play hyperparameter had been tuned
safe in one place but not two others that shared the same default), and
the browser board could throw on a reset/opponent-switch race (a stale
`setTimeout` firing a bot move against the wrong game). Both were
reproduced first, then fixed, then re-verified with scripted regression
repros.

## Stretch feature: REINFORCE on CartPole

`bellman/reinforce.py` trains a hand-rolled 2-layer softmax policy
network (manual forward pass, manual backpropagation, no autodiff engine
of any kind — verified against finite differences in
`bellman/gradcheck.py`) with the REINFORCE Monte Carlo policy-gradient
algorithm. A freshly-initialized policy survives ~10-20 of CartPole's 200
possible steps; after 5000 episodes of batched REINFORCE it survives the
full 200 in 94% of 200 held-out greedy evaluation episodes (avg 199.3/200
steps), verified stable across 5 independent training seeds (82.5%-100%
success rate each). The visualizer's third tab plays back a real trained
rollout and shows the actual learning curve (periodic greedy evaluation,
not the noisy training-episode returns, which stay flat even after the
policy has secretly converged — see the chart's own caption).

This replaced an original attempt at Mountain Car, which turned out to
defeat vanilla REINFORCE outright (sparse reward, 0 random-policy
successes in 3000 tries, verified directly) — the full investigation,
including a real divergence bug caught by inspecting weight norms
mid-training, is in [REVIEW.md](REVIEW.md)'s Phase 4 addendum.

## Polish

Input validation: `viz_export.py`'s CLI now rejects too-low episode
counts with a clear `argparse` error instead of an assertion stack trace
several calls deep (those episode counts are real minimums — this
pipeline's own correctness checks, like "the self-play agent never loses
to the oracle," can legitimately fail given too little training, same as
underfitting any other ML model). The browser dashboard now catches and
reports a rendering failure instead of a blank page, and the layout has
a small-screen pass (a `max-width: 480px` media query — tab bar becomes
horizontally scrollable, stat cards and the Tic-Tac-Toe board shrink
slightly) verified with Playwright at a 390px viewport (no horizontal
overflow, all three tabs).
