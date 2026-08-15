# Bellman — a reinforcement-learning laboratory, from scratch

## Concept

Every prior build in this repo that touches "learning" has been supervised:
Cotangent trains an MLP to fit labeled data via backprop, Loom/Sprout train a
transformer to predict the next token, VecNN indexes vectors nobody had to
earn. None of them face the problem that defines *reinforcement learning*:
an agent that has no labels at all, only a reward signal it receives after
acting, and has to discover — through trial, error, and the temporal-credit-
assignment problem — which of its own past decisions were actually
responsible for a payoff that might arrive many steps later.

Bellman is a from-scratch RL lab that implements that whole loop: real
environments with real dynamics (a hand-simulated CartPole physics ODE, a
stochastic GridWorld/Cliff-Walking MDP, a Blackjack card game), a
dynamic-programming oracle that computes the *provably optimal* policy via
the Bellman optimality equation (so every learning algorithm has ground
truth to be graded against — this repo's favorite verification pattern),
and three families of model-free RL algorithms (TD control, Monte Carlo
control, policy-gradient) that have to *rediscover* that optimum from reward
alone. A hand-rolled scalar autodiff engine (in the spirit of Cotangent, but
written fresh for this project) backs a tiny neural-net policy so REINFORCE
can control CartPole's continuous state space, where a table has no cells to
fill in.

## Why it's interesting

- **A genuinely new domain for this repo.** Every previous "agent" build
  (Kinesis' evolving creatures) used a *genetic algorithm* — global,
  population-based, gradient-free, no notion of a value function. RL is a
  different animal: a single lifelong agent, an explicit credit-assignment
  problem (which action, how many steps ago, caused this reward?), and a
  mathematical fixed point (the Bellman equation) that every algorithm here
  either solves directly (DP) or approximates by sampling (TD/MC/PG).
- **A built-in, hard verification story.** GridWorld is small enough that
  Value Iteration finds the exact optimal value function and optimal policy
  by brute dynamic programming — that becomes the oracle. Q-Learning and
  SARSA, trained purely from wandering around and collecting reward with no
  access to the transition model, are then checked against that oracle:
  do they converge to the *same* greedy policy and (within tolerance) the
  *same* value function? This is the same "ground truth vs. learned"
  discipline as Backjump's DRUP proofs or Lumina's analytic light-transport
  checks, applied to control theory instead of logic or physics.
- **Real physics, no shortcuts.** CartPole's dynamics come from the actual
  nonlinear equations of motion for a pole hinged on a cart (semi-implicit
  Euler integration of the classical Barto–Sutton–Anderson formulation) —
  not a lookup table, not a canned Gym import (no `gymnasium`/`gym`
  dependency anywhere).
- **Function approximation, not just tables.** REINFORCE needs a
  differentiable policy over a *continuous* 4D state (cart position/velocity,
  pole angle/angular velocity), so this build needs its own scalar autodiff
  + small MLP + softmax policy + log-derivative policy-gradient estimator,
  built from first principles.

## Architecture

```
bellman/
  autodiff.py     # scalar Value node + backprop (+,-,*,/,exp,log,tanh,relu) — feeds the MLP
  nn.py           # tiny MLP (Linear layers, softmax policy head) on top of autodiff
  envs.py         # Env base class (reset/step/action_space/observation description)
                   #   - GridWorldEnv (customizable grid, cliff-walking variant, stochastic slip)
                   #   - CartPoleEnv (real nonlinear ODE, semi-implicit Euler)
                   #   - BlackjackEnv (stochastic infinite-deck card game)
  dp.py           # Value Iteration + Policy Iteration over an explicit MDP model
                   #   -> the ground-truth oracle used to grade every learned policy
  td.py           # Q-Learning (off-policy) and SARSA (on-policy) tabular TD control
  mc.py           # First-visit Monte Carlo control with epsilon-greedy exploration
  pg.py           # REINFORCE policy-gradient agent (MLP policy + autodiff backprop)
  eligibility.py  # SARSA(lambda) with eligibility traces (stretch)
  train.py        # training loops, episode logging, reward-curve recording
  report.py       # builds the self-contained interactive HTML visualizer (no CDN)
  cli.py          # `bellman` command-line entry point

tests/            # unit + convergence + differential (vs DP oracle) test suite
viz/              # generated HTML output lands here
demo.sh           # exercises every required + stretch feature end-to-end
```

Design principle carried over from this repo's past builds: pure Python 3
stdlib only for every algorithm (no NumPy, no PyTorch, no `gymnasium`/`gym`)
— the autodiff engine, the MLP, the physics integrator, and the DP solver
are all hand-written. The HTML visualizer is a single self-contained file
(inline SVG/CSS/JS, no external assets, no build step); a JS mirror of the
CartPole physics drives the live browser animation.

## Feature list

**Required (core, must work end-to-end):**

1. **Tabular TD control — Q-Learning + SARSA on GridWorld/Cliff-Walking.**
   Off-policy and on-policy temporal-difference control, epsilon-greedy
   exploration with decay, learning-rate schedules, trained on a stochastic
   (slippery) grid MDP with a cliff hazard. Demonstrates the textbook
   Q-Learning-hugs-the-cliff / SARSA-takes-the-safe-path divergence.

2. **Value Iteration + Policy Iteration DP oracle.** Given the *exact* MDP
   model (transition probabilities + reward function — something the TD/MC
   agents are never shown), compute the provably optimal value function and
   policy via the Bellman optimality equation. This is the ground truth
   every learned policy in feature 1 and 3 gets graded against — bit-level
   agreement on the greedy action per state, and value-function error within
   a tight numeric tolerance.

3. **CartPole physics + REINFORCE policy-gradient control.** A from-scratch
   nonlinear pole-balancing ODE (no physics library) paired with a
   from-scratch scalar-autodiff MLP policy trained by REINFORCE
   (Monte-Carlo policy gradient with a baseline). Success is measured
   empirically: the trained policy must balance the pole for a sustained
   number of steps, verified by running many held-out episodes.

4. **Interactive HTML visualizer.** A single self-contained page: live
   reward-curve charts for every trained agent, a GridWorld Q-value heatmap
   with policy arrows that can be scrubbed across training checkpoints, and
   a live CartPole balancing animation (JS mirror of the physics, driven by
   the exported trained policy weights) with play/pause/speed controls.

**Stretch (2+, implement at least 1) — all 3 shipped:**

5. ✅ **Monte Carlo Exploring Starts control on Blackjack**, compared against
   an independently-computed optimal Blackjack policy (exact expected-value
   backward induction over the dealer's outcome distribution — a second,
   separate ground truth besides the GridWorld DP oracle, sharing no code
   with `dp.py`'s Value/Policy Iteration). 100% agreement at 500k episodes.

6. ✅ **SARSA(λ) with eligibility traces** (`bellman/td.py::sarsa_lambda`),
   trained and charted alongside plain Q-Learning/SARSA in every GridWorld
   run and the HTML report.

7. ✅ **Full CLI** — shipped as `bellman {oracle,gridworld,cartpole,
   blackjack,viz,demo}` (renamed from the originally-planned
   `train/eval/compare` split once the actual subcommands took shape — one
   verb per experiment domain reads clearer than one verb per lifecycle
   stage) with `argparse`-validated input, clean non-traceback error
   messages, and sane exit codes.

## Verification plan (Phase 5 preview)

- Differential check: greedy policy extracted from learned Q-tables (post
  convergence) matches the DP oracle's optimal policy on non-tied states;
  value estimates within a numeric tolerance band.
- CartPole: trained REINFORCE policy must sustain balance for a defined
  step threshold, averaged over N held-out episodes, well above a random
  baseline policy.
- Blackjack MC policy compared cell-by-cell against the known optimal
  basic-strategy table.
- Full pytest/unittest suite + `demo.sh` exercising every required and
  shipped stretch feature end-to-end.
