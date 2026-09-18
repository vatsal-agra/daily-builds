# Bellman

A from-scratch reinforcement learning laboratory in pure Python — no
numpy, no `gym`/`gymnasium`, no RL or ML framework of any kind. Every
algorithm, every environment's physics, and every neural network's
forward *and* backward pass is hand-written and independently verified
(exact dynamic-programming oracles, finite-difference gradient checks, a
perfect game-tree search, and a 37-test suite).

## What it is

Three genuinely different ways of exploiting the same recursive identity
— **the value of a state is the immediate reward plus the discounted
value of wherever you land next** (the Bellman equation, the project's
namesake) — applied to three different problems:

1. **Cliff Walking** (a 4x12 gridworld): solved exactly by dynamic
   programming (Policy Iteration and Value Iteration, which independently
   agree on the optimal value), and separately *learned* by two flavors
   of tabular temporal-difference control, SARSA and Q-learning, from raw
   trial-and-error experience alone.
2. **Tic-Tac-Toe**: solved exactly by a memoized negamax game-tree search
   (a provably perfect, never-losing opponent), and separately *learned*
   by a TD(0) self-play agent that trains purely by playing itself
   thousands of times, with no minimax knowledge ever injected.
3. **CartPole**: a continuous 4-dimensional control task with no tabular
   representation possible, learned by REINFORCE — a Monte Carlo policy
   gradient method that trains a small neural network (hand-derived
   forward and backward pass, gradient-checked against finite
   differences) directly from whole-episode returns.

Every learned result has a ground-truth or an adversarial check to prove
it isn't just "looks plausible": Q-learning's greedy policy is checked to
match the DP-computed optimum *exactly*; SARSA's is checked to reproduce
the textbook Sutton & Barto safe-vs-risky-path split; the self-play agent
is checked to never lose a single game (across 600 randomized games as
both sides) to the perfect minimax oracle; REINFORCE's trained policy is
checked against a freshly-initialized baseline on the same evaluation.

## How to run it

```bash
cd 2026-09-18-bellman

# Regenerate every result from scratch (DP, TD control, self-play,
# REINFORCE) and export it for the visualizer. Takes about 15 seconds.
python3 -m bellman.viz_export

# Open the interactive dashboard. Opening visualizer/index.html directly
# (double-click) also works -- the data is inlined as a plain .js file so
# there's no fetch()-of-local-JSON to trip over file:// CORS blocks.
python3 -m http.server 8000
# then open http://localhost:8000/visualizer/

# Run everything end to end (unit tests, gradient check, the full
# production pipeline, and a 7-check headless-browser suite against the
# real dashboard) with a final PASS/FAIL summary:
./demo.sh
```

No dependencies beyond Python 3's standard library for anything under
`bellman/`. `demo.sh`'s browser checks use Playwright (already available
in this environment) to drive real headless Chromium against the actual
HTML artifact — not a mock.

## Feature list

**Required (all four fully working, cross-verified):**

1. Cliff Walking MDP + exact DP oracle (Policy Iteration and Value
   Iteration, independently agreeing: V\*(start) = -13).
2. Tabular SARSA vs Q-learning, reproducing the textbook on-policy/
   off-policy split (Q-learning matches the DP optimum exactly; SARSA
   takes the longer, safer route) plus a SARSA(λ) eligibility-trace
   variant that reaches a working policy in far fewer episodes than
   1-step SARSA at matched hyperparameters.
3. A memoized negamax perfect Tic-Tac-Toe oracle (5478 reachable states,
   always draws against itself) plus a TD(0) self-play learner that
   never loses to it.
4. `viz_export.py` + `visualizer/index.html`: a real, self-contained,
   interactive dashboard (value heatmaps, policy arrows, trajectory
   playback, training curves, and a live Tic-Tac-Toe board you can play
   against either learned agent) — not a static screenshot.

**Stretch:**

5. REINFORCE policy gradient on CartPole, with a hand-rolled, gradient-
   checked policy network (see below — this replaced an original Mountain
   Car attempt that turned out to defeat vanilla REINFORCE outright).
6. SARSA(λ) (folded into required feature 2 above once built, since it
   shares the same TD control module and Cliff Walking oracle).

## Why this, today

Every prior "learns" build in this repo's history has been supervised
(nine from-scratch Transformers trained on a fixed labeled corpus,
Cotangent's scalar-autodiff MLP fit to a dataset) or population-based
search (Kinesis's genetic algorithm evolving creatures). None had an
agent that acts in an environment with no labeled right answer, gets a
reward that may arrive many steps after the decision that earned it, and
has to learn purely from that trial-and-error signal while balancing
exploration against exploitation. Reinforcement learning is that missing
shape, and the Bellman equation is an unusually well-verified spine to
build it on: dynamic programming gives a *provably optimal* value
function to check learned methods against, not just a "looks plausible"
result, and Cliff Walking additionally has a famous, precisely documented
qualitative result (the SARSA/Q-learning path split) to reproduce on
purpose as a strong correctness signal no amount of "it ran without
crashing" can fake.

## What actually happened building it (short version — full detail in [REVIEW.md](REVIEW.md))

Phase 3's adversarial review found and fixed two real, reproduced bugs:
the documented `python -m bellman.viz_export` one-liner crashed on a
stale hyperparameter default that had been tuned safe in one place but
not two others sharing it, and the browser board could throw on a
reset-mid-turn race (a stale `setTimeout` firing a bot move against the
wrong game).

Phase 4's stretch feature took a real detour: Mountain Car (the original
plan) turned out to defeat vanilla REINFORCE outright — its sparse -1/tick
reward gives a random policy 0 successes in 3000 tries (verified
directly), so there was never a single success for REINFORCE to
reinforce. Reward shaping, action-repeat, and a from-scratch entropy
bonus all failed to fix it, and the process caught a genuine gradient
divergence bug along the way (parameter norms into the thousands,
directly measured) before concluding the task itself, not the algorithm,
needed to change. CartPole — the standard first benchmark for
policy-gradient methods for exactly the opposite reason (dense reward,
no exploration wall) — replaced it and works well: 94% greedy success
rate after training (0% untrained), stable across 5 independent seeds.

Phase 5's test suite then found two *more* real bugs beyond the Phase 3
review: `minimax.best_moves()` didn't check for an already-terminal board
before searching it (unreachable from any shipped code path, but a real
contract violation), and `CartPole` carried a hidden step-counter on
`self` that crashed if `step()` was ever called before `reset()` —
refactored to a fully stateless `step(state, action)`, matching
`CliffWalking`'s pattern, with the episode-length cutoff moved to the
caller where it belongs.

## Where a human could take this next

- **Actor-Critic / a learned baseline.** REINFORCE's biggest remaining
  weakness is variance; a from-scratch value-function critic (even a
  small linear one) would cut training time and likely make Mountain
  Car tractable after all, closing the loop this build's REVIEW.md left
  open.
- **Function approximation for Cliff Walking / Tic-Tac-Toe.** Both are
  currently tabular; swapping the Q-table or self-play value table for a
  small neural network (reusing `reinforce.py`'s hand-rolled network
  machinery) would be a natural bridge to the "deep RL" literature.
- **A harder game for self-play.** Tic-Tac-Toe's 5478-state space is
  small enough to fully memoize; Connect Four or a small-board Go variant
  would force genuine generalization instead of eventually memorizing
  (almost) the whole state space, as this build's agent does (99% of all
  reachable states).
- **Multi-agent Cliff Walking or a predator-prey gridworld**, extending
  this repo's Matchbook/Concord/Vein lineage of multi-agent systems into
  one where the agents themselves are learning, not just interacting
  under fixed rules.
- **True Nakamoto-style adversarial self-play** — an opponent that
  actively tries to exploit weaknesses in the learned Tic-Tac-Toe agent's
  value estimates (rather than the randomized-but-still-optimal oracle
  used here) to find the worst-case remaining gaps in its ~99% state
  coverage.
