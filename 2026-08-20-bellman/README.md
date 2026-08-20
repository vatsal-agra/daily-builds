# Bellman

A reinforcement learning toolkit built entirely from scratch — no `gym`,
no `stable-baselines3`, no `torch`/`tensorflow`. Tabular Q-learning, SARSA,
a Deep Q-Network, and REINFORCE, all training inside from-scratch
environments (GridWorld/Cliff Walking, CartPole).

**Status: Phase 5 (verification) complete.** All 4 required features plus
both planned stretch features (the interactive HTML report and the DQN
ablation study) are implemented, verified, and polished. A hostile review
pass found and fixed 5 real bugs (see [REVIEW.md](REVIEW.md)). `demo.sh`
runs the full 102-test suite, a real end-to-end training run of every
agent, builds the HTML report, and exercises 7 CLI-robustness checks —
run twice back to back, every RL number came back byte-identical (only
wall-clock timing differed), confirming the whole pipeline is genuinely
deterministic given a seed, not just "usually reproducible".

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
