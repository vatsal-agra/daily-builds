# Bellman

**Status: Phase 3 — adversarial review complete.** Found and fixed 3 real
bugs (a `CartPoleEnv` crash on `step()` before `reset()`, a CLI crash on
`--episodes 0`, a private-attribute leak in the report builder) and
documented 2 things that looked suspicious but checked out as deliberate.
Full writeup in [REVIEW.md](./REVIEW.md).

A from-scratch reinforcement-learning library: discrete MDP environments
solved exactly by dynamic programming, tabular Q-learning/SARSA/Monte-Carlo
agents checked for convergence against that exact solution, a from-scratch
continuous-state cart-pole physics environment, and a Deep Q-Network that
learns to balance it from raw state — no gym, no stable-baselines, no
PyTorch/TensorFlow/JAX.

See [PLAN.md](./PLAN.md) for the full architecture and feature list.

## What's implemented so far

- `bellman/envs/gridworld.py` — GridWorld, CliffWalking, WindyGridworld,
  FrozenLake, all built on one configurable MDP with a real, enumerable
  transition/reward model.
- `bellman/envs/cartpole.py` — the classic nonlinear cart-pole ODE,
  integrated from scratch with semi-implicit Euler.
- `bellman/agents/dp.py` — value iteration + policy iteration, the exact
  ground-truth oracle.
- `bellman/agents/tabular.py` — Q-learning, SARSA, every-visit Monte
  Carlo control.
- `bellman/agents/nn.py` — a small hand-derived MLP (forward/backward/
  Adam), gradient-checked against finite differences.
- `bellman/agents/dqn.py` — Deep Q-Network (replay buffer, target
  network, Double DQN target, state normalization, Huber loss).
- `bellman/cli.py` — `python -m bellman.cli {dp,tabular,cliff-compare,
  dqn,reinforce,report}`.

## Try it

```
python -m bellman.cli dp gridworld
python -m bellman.cli tabular qlearning cliffwalking
python -m bellman.cli cliff-compare
python -m bellman.cli dqn --episodes 260
```

## Tests

```
python -m unittest discover -s tests
```

REINFORCE (`bellman/agents/reinforce.py`) landed alongside the core build
and is already tested end to end. Remaining phases (interactive HTML
report, polish, verification/demo script, ship) still to come — this
README will be replaced with the final version at the end.
