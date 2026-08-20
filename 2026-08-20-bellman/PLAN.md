# Bellman — Reinforcement Learning From Scratch

## Concept

A from-scratch reinforcement learning toolkit: tabular Q-learning and SARSA,
a Deep Q-Network (DQN) with experience replay and a target network, and a
policy-gradient agent (REINFORCE) — all implemented with hand-derived math,
no `gym`/`stable-baselines3`/`torch`/`tensorflow`. Every agent trains inside
custom-built environments (a GridWorld/Cliff-Walking MDP and a physically
simulated CartPole) that are themselves implemented from scratch, so nothing
in the pipeline — environment, function approximator, optimizer, or agent —
is a black box.

## Why this is interesting

This repository has an enormous back-catalog of "from scratch" builds —
autodiff engines, transformer language models (nine separate "Loom"
entries), evolutionary creature simulators, SAT/CDCL solvers, physics
engines, path tracers, compilers, VCS systems, crypto suites, search
engines. Every one of those either (a) predicts/generates from a fixed
dataset (supervised learning — the transformers, the autodiff MLP in
Cotangent) or (b) evolves a *population* of static candidates via a genetic
algorithm with no learning signal fed back into a single agent's decisions
(Kinesis's creature evolution). **Reinforcement learning — a single agent
that acts, observes a reward, and updates its own decision policy from that
feedback loop — has never appeared in this ledger.** It is a genuinely
different learning paradigm: no labeled targets exist anywhere, credit for
a reward received at the end of an episode has to be propagated backward
through a sequence of earlier decisions (the "credit assignment problem"),
and the agent's own changing behavior determines the distribution of data
it trains on next (a moving target that famously destabilizes naive neural
function approximation — which is *why* DQN needs its two signature tricks,
and this build demonstrates that in an ablation, not just asserts it).

It also has one of the best-known "textbook" reproducible results in all of
RL to use as ground truth: on the classic Cliff Walking task (Sutton &
Barto, *Reinforcement Learning: An Introduction*, Example 6.6), off-policy
Q-learning converges to the *optimal* but risky path along the cliff edge,
while on-policy SARSA converges to a *safer, longer* path — because SARSA's
updates account for the exploratory policy's own chance of stepping off the
cliff. Reproducing that exact qualitative divergence from two agents that
share every hyperparameter except their update rule is a strong, legible
correctness signal that a numeric loss curve alone can't give.

## Architecture

```
bellman/
  envs/
    gridworld.py     # tabular GridWorld + the classic Cliff Walking variant
    cartpole.py       # from-scratch cart-pole physics (Euler integration)
  agents/
    nn.py             # hand-rolled MLP: forward pass + manually derived
                       # backprop equations (no autodiff graph) — a Linear/
                       # ReLU stack with its own gradient descent step
    qlearning.py       # tabular Q-learning and SARSA (shared update loop,
                       # different target computation — the on/off-policy
                       # split lives in one obvious place)
    dqn.py             # DQN: replay buffer, target network, epsilon decay
    reinforce.py        # Monte Carlo policy gradient with a value baseline
  value_iteration.py    # exact dynamic-programming solver — ground truth
                         # for verifying Q-learning/SARSA convergence
  train.py               # CLI: train/eval any agent on any env, JSON logs
  viz.py                  # renders the interactive HTML report from logs
tests/                     # unit + convergence + differential tests
demo.sh                    # trains every agent, runs the full suite, builds
                            # the HTML report, all from a clean checkout
```

Data flow: an `Env` exposes `reset() -> state` and `step(action) -> (state,
reward, done, info)`. Tabular agents index a `dict`/array Q-table directly
off discrete state ids. DQN and REINFORCE call a shared `nn.MLP` for
function approximation over CartPole's continuous 4D state. `train.py`
runs an agent against an env for N episodes, logging per-episode return,
steps, and (for DQN) loss to a JSON file under `results/`. `viz.py` turns
those JSON logs into a single self-contained HTML page: learning curves,
a live-replayed Q-value heatmap over the grid, and a canvas replay of a
trained CartPole episode.

## Feature list

**Required (4):**
1. **Tabular Q-learning** on GridWorld, converging to the value-iteration
   ground-truth optimal policy (verified state-by-state, not just "reward
   went up").
2. **SARSA** (on-policy TD control) on the same environments, sharing the
   update-loop scaffold with Q-learning but differing in exactly the target
   computation — verified to reproduce the textbook Cliff Walking
   divergence from Q-learning (safer path vs. optimal-but-risky path).
3. **Deep Q-Network (DQN)** — a hand-rolled MLP Q-function, experience
   replay buffer, target network with periodic sync, epsilon-greedy
   exploration with decay — trained on CartPole to a defined "solved"
   average-return threshold.
4. **REINFORCE** (Monte Carlo policy gradient) with a learned value
   baseline for variance reduction, trained on CartPole from the same
   from-scratch MLP.

**Stretch (2+):**
5. **Interactive HTML report** — learning-curve charts for every agent/env
   pair, a live Q-value heatmap replay over the GridWorld showing the
   policy's arrows converge over training, and a canvas replay of a
   trained CartPole episode (real physics frames, not a canned animation).
6. **DQN ablation study** — trains DQN with replay-buffer and/or
   target-network disabled and reports the measured instability/divergence
   this causes, next to the full DQN's stable convergence — turning "these
   tricks matter" from an assertion into a reproducible, graphed result.

## Verification strategy

- Tabular Q-learning/SARSA Q-values and greedy policies checked against an
  exact value-iteration solve of the same MDP (small enough to solve
  exactly).
- Cliff Walking Q-learning-vs-SARSA path divergence checked structurally
  (Q-learning's greedy path touches the cliff-adjacent row; SARSA's does
  not) — a differential test between two agents, not a single number.
- The hand-rolled MLP's backprop gradients checked against central
  finite-difference numerical gradients before any agent is trusted to
  train with it.
- DQN and REINFORCE both required to cross a defined CartPole "solved"
  return threshold over held-out evaluation episodes, using a fixed
  evaluation seed set (no cherry-picked run).
