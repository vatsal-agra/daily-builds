# Bellman

A reinforcement learning toolkit built entirely from scratch — no `gym`,
no `stable-baselines3`, no `torch`/`tensorflow`. Tabular Q-learning, SARSA,
a Deep Q-Network, and REINFORCE, all training inside from-scratch
environments (GridWorld/Cliff Walking, CartPole).

**Status: Phase 3 (adversarial review) complete.** All 4 required
features — tabular Q-learning, SARSA, DQN, and REINFORCE — are
implemented and demonstrably working end to end, verified against exact
value iteration (GridWorld), the textbook Cliff Walking on/off-policy
divergence, and finite-difference gradient checks (the hand-rolled MLP).
A hostile review pass found and fixed 4 real bugs (including one in the
gradient-checking test scaffolding itself) plus CLI validation gaps —
see [REVIEW.md](REVIEW.md) for the full writeup. 99/99 tests green. See
[PLAN.md](PLAN.md) for the full design.

## Quickstart

```
pip install -r requirements.txt
python -m unittest discover -s tests
python -m bellman.train demo      # trains everything, prints a summary
python -m bellman.viz             # builds report.html from results/*.json
```

Individual commands (`python -m bellman.train <name> --help`):
`qlearning`, `sarsa`, `cliff-compare`, `dqn`, `reinforce`, `ablation`.

Full usage instructions, the feature list, results, and the "why this
project" writeup will be finished out in README.md as later phases land.
