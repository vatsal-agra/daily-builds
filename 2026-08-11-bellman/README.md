# Bellman

A from-scratch reinforcement-learning library and study: discrete MDP
environments solved *exactly* by dynamic programming, tabular agents
(Q-learning, SARSA, Monte Carlo) checked for convergence against that
exact ground truth, a from-scratch continuous-state cart-pole physics
environment, and two structurally different function-approximation
agents (Deep Q-Network, REINFORCE) that learn to balance it from raw
state. No `gym`, no `stable-baselines`, no PyTorch/TensorFlow/JAX — the
neural net's forward/backward pass, the physics, the MDP solvers, and
every learning algorithm are hand-written and gradient/oracle-checked.

Every prior build in this repo that "learns" has learned by
*supervision* — nine from-scratch transformers and an autodiff engine
all fit a model to labeled targets computed in advance. Nothing here has
learned purely from trial and error against its own consequences before.
See [PLAN.md](./PLAN.md) for the full rationale and architecture.

## Why this, today

Reinforcement learning is the one major branch of machine learning this
repo hadn't touched, and the gridworld half of it is a perfect fit for
the "verify against ground truth" discipline the rest of the repo has
built up: value iteration gives an *exact*, provably-optimal policy for
every discrete environment here, so the tabular agents aren't just
"looked like they learned" — their final greedy policy is checked
state-by-state against that exact answer. Cart-pole has no such closed
form (a real nonlinear ODE), which is exactly why it needs function
approximation, and is the harder, more interesting half of the build.

## What's here

```
bellman/
  envs/gridworld.py   GridWorld, CliffWalking, WindyGridworld, FrozenLake
                       -- one configurable MDP, full P(s'|s,a) model
  envs/cartpole.py     the classic nonlinear cart-pole ODE, from scratch
  agents/dp.py         value iteration + policy iteration (the oracle)
  agents/tabular.py    Q-learning, SARSA, every-visit Monte Carlo control
  agents/nn.py         hand-derived MLP: forward/backward/Adam
  agents/dqn.py        Deep Q-Network: replay buffer, target net, Double
                        DQN target, state normalization, Huber loss
  agents/reinforce.py  Monte-Carlo policy gradient with a learned baseline
  viz/report.py        builds report.html from a real end-to-end run
  cli.py               `python -m bellman.cli ...`
tests/                 91 tests: DP-oracle hand checks, transition-model
                        checks, tabular convergence-to-optimal, NN
                        gradient checks vs. finite differences, DQN/
                        REINFORCE end-to-end training with hard numeric
                        pass bars, CLI subprocess smoke tests
demo.sh                 runs everything end to end
```

## Try it

```bash
python -m bellman.cli dp gridworld              # exact V*/policy via value iteration
python -m bellman.cli tabular qlearning gridworld
python -m bellman.cli cliff-compare             # Q-learning vs SARSA divergence
python -m bellman.cli dqn --episodes 260
python -m bellman.cli reinforce --episodes 350
python -m bellman.cli report --out report.html  # build the interactive HTML report
```

```bash
python -m unittest discover -s tests            # full test suite
./demo.sh                                        # tests + every CLI command + report, end to end
```

## Feature list

**Required (all 4 shipped, fully working end to end):**

1. **Discrete MDP environments solved exactly** — GridWorld,
   CliffWalking, WindyGridworld, FrozenLake, all one configurable
   `GridWorld` MDP with a real, enumerable transition/reward model, plus
   a value-iteration/policy-iteration oracle used as ground truth
   everywhere else.
2. **Tabular TD/Monte-Carlo agents** — Q-learning, SARSA, every-visit
   Monte Carlo control, epsilon-greedy with decay, checked for exact
   convergence to the DP oracle's optimal policy on GridWorld (12/12
   states for Q-learning), and reproducing the textbook on-policy/
   off-policy divergence on CliffWalking (Q-learning walks the cliff
   edge, SARSA stays away — both verified in `tests/test_tabular_agents.py`).
3. **From-scratch continuous-state cart-pole physics** — the real
   nonlinear cart-pole ODE (Barto/Sutton/Anderson 1983), semi-implicit
   Euler integration — a genuinely new physics domain for this repo (a
   single controlled dynamical system, not rigid-body collision like
   Tumble/Impulse/Kinesis).
4. **Deep Q-Network** — a purpose-built, hand-derived 2-hidden-layer MLP
   (gradient-checked against finite differences to 1e-12), experience
   replay, a periodically-synced target network, a Double DQN target,
   Huber loss, and state normalization — trained to balance the pole for
   **~120 steps on average** (measured, seed 0; random play averages
   ~15-20) at a hard numeric pass bar checked in `tests/test_dqn.py`.

**Stretch (both shipped):**

5. **REINFORCE** — Monte-Carlo policy gradient with a learned, normalized
   baseline. Structurally different from DQN in every way that matters
   (on-policy vs. off-policy, full-episode return vs. one-step TD
   bootstrap, learns a policy directly vs. deriving one from a value
   function) — and **measurably better** on this task: a 30-episode
   greedy evaluation averages **~460/500 steps** (vs. DQN's ~120). Both
   are correctly implemented; see [REVIEW.md](./REVIEW.md) for why the
   gap is real and not a bug.
6. **Interactive HTML report** (`bellman/viz/report.py`) — a real value-
   iteration heatmap + policy-arrow overlay per gridworld next to live
   reward curves for all three tabular agents, a replayable animation of
   each agent's learned greedy path, a static Q-learning-vs-SARSA
   CliffWalking path comparison, and side-by-side DQN/REINFORCE training
   curves with a replayable cart-pole swing animation — all self-
   contained (no CDN), theme-aware (light/dark), and verified with a
   headless-Chromium console-error check.

## Adversarial review

Phase 3 found and fixed 5 real issues — a `CartPoleEnv.step()` crash with
a confusing raw error if called before `reset()`, a CLI crash on
`--episodes 0`, a silently-dropped final data point in the report's
chart downsampler, a private-attribute leak, and a self-deceiving test
that wasn't testing what it claimed. Full writeup, reproduction steps,
and the design choices that were double-checked (not bugs) but worth
explaining — including the honest DQN-vs-REINFORCE performance gap — are
in [REVIEW.md](./REVIEW.md).

## Where a human could take this next

- **Prioritized experience replay** for DQN — the single most likely
  fix to close the gap with REINFORCE; this implementation samples
  uniformly.
- **N-step returns / TD(lambda)** for the tabular agents, bridging
  Q-learning/SARSA's one-step bootstrap and Monte Carlo's full-episode
  return.
- **A second continuous-control task** (mountain car, acrobot) to see
  whether REINFORCE's advantage here is task-specific or general.
- **Actor-critic** (combining DQN's bootstrapping with REINFORCE's direct
  policy learning) as the natural next algorithm after having both
  pieces already built.
- **A GPU/NumPy batched forward pass** for the neural net — the current
  `bellman/agents/nn.py` is plain-list Python by design (consistency with
  the rest of this repo, easy to gradient-check by hand), which is the
  main reason DQN training takes minutes rather than seconds.
