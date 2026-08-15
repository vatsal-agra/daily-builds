# Bellman

A reinforcement-learning laboratory built entirely from scratch in pure Python —
no NumPy, no PyTorch/TensorFlow/JAX, no `gym`/`gymnasium`. Every algorithm,
environment, and neural net is hand-written and checked against independent
ground truth wherever one exists.

**Status: Phase 2 — core build complete.** All 4 required features work
end-to-end (see verification numbers below). Adversarial review, stretch
features, and final polish are still to come.

## What's here so far

- **Dynamic-programming oracle** (`bellman/dp.py`): Value Iteration and
  Policy Iteration solve GridWorld's Bellman optimality equation exactly,
  given the true transition model. This is the ground truth every learned
  policy below is graded against.
- **Tabular TD control** (`bellman/td.py`): Q-Learning (off-policy) and
  SARSA (on-policy), trained purely from `env.step()` samples — never given
  the transition model. On Cliff Walking, Q-Learning converges to *exactly*
  the DP-optimal return (-13); SARSA converges to the classic "safer path"
  result.
- **REINFORCE policy gradient** (`bellman/pg.py`) on a from-scratch
  **CartPole** physics simulation (`bellman/envs.py`), backed by a
  hand-rolled **scalar autodiff engine** (`bellman/autodiff.py`) and tiny
  MLP (`bellman/nn.py`). A trained policy sustains ~495/500 steps after 150
  episodes, vs. ~18 steps for a random policy.
- **Interactive HTML report** (`bellman/report.py` + `bellman viz`): reward
  curves, a scrubbable GridWorld Q-value heatmap with policy arrows, and a
  live in-browser CartPole animation (JS mirrors of both the physics and the
  trained network's forward pass — no server).

## Quickstart

```bash
cd 2026-08-15-bellman
python3 -m bellman.cli oracle                 # solve GridWorld exactly (DP)
python3 -m bellman.cli gridworld --episodes 500   # Q-Learning / SARSA / SARSA(λ)
python3 -m bellman.cli cartpole --episodes 400    # REINFORCE on CartPole
python3 -m bellman.cli blackjack --episodes 500000  # Monte Carlo Exploring Starts
python3 -m bellman.cli viz --out viz/report.html    # build the interactive report
python3 -m unittest discover -s tests -v            # run the test suite
```

See [`PLAN.md`](./PLAN.md) for the full concept, architecture, and feature
list. This README will be filled out further (full feature list, "why this
today", "where to take it next") once the remaining phases land.
