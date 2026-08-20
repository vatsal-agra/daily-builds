# Bellman

A reinforcement learning toolkit built entirely from scratch — no `gym`,
no `stable-baselines3`, no `torch`/`tensorflow`. Tabular Q-learning, SARSA,
a Deep Q-Network, and REINFORCE, all training inside from-scratch
environments (GridWorld/Cliff Walking, CartPole).

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both planned stretch features (the interactive HTML report and the
DQN ablation study) are implemented, verified, and polished. A hostile
review pass across Phases 3–4 found and fixed 5 real bugs (including a
convention mismatch in the gradient-checking test scaffolding itself and
a path-traversal gap in `--name`) — see [REVIEW.md](REVIEW.md) for the
full writeup. 102/102 tests green.

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
