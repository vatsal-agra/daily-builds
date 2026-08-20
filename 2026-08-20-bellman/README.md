# Bellman

A reinforcement learning toolkit built entirely from scratch — tabular
Q-learning, SARSA, a Deep Q-Network (DQN), and REINFORCE (Monte Carlo
policy gradient), all training inside environments (GridWorld, Cliff
Walking, CartPole) also implemented from scratch. No `gym`, no
`stable-baselines3`, no `torch`/`tensorflow` — the neural-network function
approximator is a hand-rolled MLP with manually derived backprop
equations, checked against numerical finite-difference gradients before
any agent is trusted to learn with it.

**Status: shipped.** 4/4 required features + 2/2 stretch features. 102
tests green. `demo.sh` runs the whole thing end to end.

## Why this, today

This repository has an enormous back-catalog of "from scratch" builds —
autodiff engines, nine separate transformer language models, evolutionary
creature simulators, SAT solvers, physics engines, path tracers,
compilers, VCS systems. Every one of those is either **supervised
learning** (predict/generate from a fixed dataset — the transformers,
Cotangent's autodiff MLP) or **evolutionary search** over a *population*
of static candidates with no learning signal fed back into any single
candidate's decisions (Kinesis's creature evolution). **Reinforcement
learning — a single agent that acts, observes a reward, and updates its
own decision policy from that feedback loop — has never appeared in this
ledger.** It's a genuinely different learning paradigm: there are no
labeled targets anywhere, credit for a reward received at the end of an
episode has to be propagated backward through a sequence of earlier
decisions (the credit-assignment problem), and the agent's own changing
behavior determines the distribution of data it trains on next — a moving
target that famously destabilizes naive neural function approximation,
which is *why* DQN needs its two signature tricks (this project measures
that instability directly, in the ablation, rather than just asserting
it).

It also comes with one of the best-known reproducible results in all of
RL to use as ground truth: on the classic Cliff Walking task (Sutton &
Barto, *Reinforcement Learning: An Introduction*, Example 6.6), off-policy
Q-learning converges to the *optimal but risky* path along the cliff
edge, while on-policy SARSA — whose updates account for its own
exploratory policy's chance of stepping off the cliff — converges to a
*safer, longer* route. Reproducing that exact qualitative divergence from
two agents sharing every hyperparameter except their update rule is a far
stronger correctness signal than a loss curve going down.

## Quickstart

```bash
pip install -r requirements.txt
python -m unittest discover -s tests   # 102 tests
python -m bellman.train demo           # trains everything, prints a summary
python -m bellman.viz                  # builds report.html from results/*.json
./demo.sh                              # does all of the above + CLI checks, end to end
```

Individual commands (`python -m bellman.train <name> --help` for flags):

| Command | What it does |
|---|---|
| `qlearning` | Tabular Q-learning on GridWorld, verified against exact value iteration |
| `sarsa` | Tabular SARSA on GridWorld, same verification |
| `cliff-compare` | Trains both on Cliff Walking, checks the on/off-policy path divergence |
| `dqn [--no-replay] [--no-target]` | DQN on CartPole, with the two stability tricks togglable |
| `reinforce` | REINFORCE (policy gradient + value baseline) on CartPole |
| `ablation [--n-seeds N]` | Trains DQN full / no-replay / no-target across N seeds each |
| `demo` | A condensed run of every command above, used by `demo.sh` |

## Feature list

**Required (4/4 shipped):**

1. **Tabular Q-learning** on GridWorld — converges to the value-iteration
   ground-truth optimal policy, verified by rolling out the learned
   greedy policy from the start state and checking it realizes the exact
   optimal discounted return (21/21 states value-consistent with V* in
   the shipped run).
2. **SARSA** — shares Q-learning's update-loop scaffold, differs in
   exactly the target computation (bootstrap off the action actually
   taken next, not the max), and reproduces the textbook Cliff Walking
   divergence: in the shipped run, Q-learning's greedy path spends **100%**
   of its interior cells on the row directly above the cliff (the risky
   optimal route); SARSA's spends **12%** (a longer, safer route via the
   top row).
3. **Deep Q-Network (DQN)** — a hand-rolled MLP Q-function, an experience
   replay buffer (backed by a ring-buffer list, not a `deque`, for O(1)
   indexed sampling — see REVIEW.md), and a periodically-synced target
   network. Shipped run: 150 episodes, eval avg return 194.6/500 on
   CartPole (held-out, greedy, fixed eval seeds).
4. **REINFORCE** — Monte Carlo policy gradient with a learned value
   baseline for variance reduction. Shipped run: 150 episodes, eval avg
   return **494.5/500** — REINFORCE converges dramatically faster than
   DQN on this task at matched episode counts, and the shipped report
   shows both curves side by side rather than picking a flattering
   comparison.

**Stretch (2/2 shipped):**

5. **Interactive HTML report** (`bellman/viz.py` → `report.html`) — real
   learning curves for every agent, a live policy-arrow overlay on the
   GridWorld (drawn from the actual learned Q-table), both Cliff Walking
   paths rendered on the same grid, and a canvas replay of a real
   recorded CartPole evaluation episode (actual physics frames, not a
   canned animation) for both DQN and REINFORCE. Self-contained, no CDN,
   no build step, no server.
6. **DQN ablation study** — trains full DQN, DQN-without-replay, and
   DQN-without-a-target-network across 3 seeds each, reporting mean ± std
   of both the held-out eval return and a **max-drawdown** instability
   metric (the largest drop from any earlier peak of the training
   moving-average return — catches "learned fine, then collapsed" even on
   a run whose *final* number happens to land okay). Shipped result:
   `no_target`'s drawdown is **168.4 ± 192.6**, more than 3x `full`'s
   **45.0 ± 13.2** and wildly less consistent — an honest, seed-robust
   demonstration of why the target network exists, not an assertion.

## Verification

- **Tabular agents vs. exact ground truth**: `bellman/value_iteration.py`
  solves each GridWorld exactly via dynamic programming; Q-learning/SARSA
  are checked against it by rollout-return, not raw Q-table comparison
  (harmless tie-breaking on states the optimal path never visits made a
  naive per-state check fail even on genuinely-converged agents).
- **Cliff Walking divergence**: checked structurally on the actual
  generated paths (fraction of interior cells in the cliff-edge row), not
  asserted from the textbook.
- **The hand-rolled MLP**: every backward-pass equation checked against
  central finite-difference numerical gradients across 5
  architectures/batch sizes — this caught a real bug (see REVIEW.md #1).
- **Environments**: `GridWorld`'s wall/cliff/edge-bump/absorbing-goal
  logic and `CartPole`'s physics (checked against an independently
  written reference implementation of the same closed-form equations of
  motion) both have dedicated unit tests, not just "it runs."
- **102/102 tests green**, including CLI-level subprocess tests that
  exercise the real `python -m bellman.train` entry point.
- **Reproducibility**: `demo.sh` run twice back to back produced
  byte-identical RL numbers (only wall-clock timing differed) — the
  whole pipeline is genuinely seeded end to end, not "usually"
  reproducible.

See [PLAN.md](PLAN.md) for the original design and [REVIEW.md](REVIEW.md)
for the adversarial review — 5 real bugs found and fixed, including a
batch-averaging convention mismatch in the gradient-checking test
scaffolding itself (the kind of bug that hides behind a green single-
example test) and a path-traversal gap in the `dqn --name` flag.

## Where a human could take this next

- **Harder environments.** Everything here is small enough to be either
  exactly solvable (GridWorld) or fast to train (CartPole). The next
  obvious step is something with real visual input (a from-scratch
  convolutional Q-network on a simple pixel-based environment) or a
  continuous action space (DDPG/SAC instead of discrete DQN/REINFORCE).
- **PPO.** REINFORCE's high variance and DQN's instability are both
  visible in this project's own results — Proximal Policy Optimization is
  the natural next algorithm precisely because it was designed to fix
  both classes of problem at once (clipped surrogate objective, GAE).
- **Multi-agent / self-play.** Kinesis (2026-07-12) evolved a population
  of static creatures; a natural combination would be self-play RL (two
  learned policies training against each other, à la AlphaGo's core
  loop) rather than evolution against a fixed fitness function.
- **A real stochastic MDP.** GridWorld/CartPole are deliberately
  deterministic here so value iteration is exact ground truth. Adding
  slip-probability transitions (classic FrozenLake-style) would be a
  natural extension once the deterministic case is trusted — and would
  need Q-learning's off-policy convergence guarantees to be re-verified
  under noise, a genuinely different check than anything in this build.
- **Bigger ablations.** The DQN ablation here isolates replay and the
  target network. Prioritized experience replay, double DQN (decoupling
  action selection from evaluation to fix Q-value overestimation), and
  dueling network architectures are all one-line-of-reasoning-away
  extensions with their own measurable, ablation-able effects.
