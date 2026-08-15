# Bellman

A reinforcement-learning laboratory built entirely from scratch in pure
Python — no NumPy, no PyTorch/TensorFlow/JAX, no `gym`/`gymnasium`. Every
algorithm, environment, physics simulation, and neural net is hand-written,
and every learned result is checked against independent ground truth
wherever one exists: a dynamic-programming oracle for GridWorld, an
independently-derived expected-value solver for Blackjack, and a
random-policy baseline for CartPole.

**Status: shipped.** 4/4 required features + 3/3 stretch features, 85/85
unit tests green, 14/14 end-to-end verification checks green (`demo.sh`).
See [`PLAN.md`](./PLAN.md) for the original design and
[`REVIEW.md`](./REVIEW.md) for the adversarial-review findings — including
a critical cross-process non-determinism bug in the autodiff engine that
only a real end-to-end run caught.

## What it is

Four connected pieces, one theme — an agent that only ever sees a reward
signal, and has to work out for itself which of its own past decisions
earned it:

1. **A dynamic-programming oracle** (`bellman/dp.py`). Value Iteration and
   Policy Iteration solve GridWorld's Bellman optimality equation *exactly*,
   given the true transition model. This is the fixed point every
   model-free algorithm below is trying to discover by trial and error, and
   the ground truth they get graded against.

2. **Tabular temporal-difference control** (`bellman/td.py`). Q-Learning
   (off-policy) and SARSA (on-policy), plus SARSA(λ) with eligibility
   traces, trained on Cliff Walking purely from `env.step()` samples — never
   given the transition model. Q-Learning's greedy policy converges to
   *exactly* the DP-optimal return (-13); SARSA converges to the classic
   "safer path" result (further from the cliff), reproducing the textbook
   divergence between the two algorithms.

3. **REINFORCE policy-gradient control** (`bellman/pg.py`) on a
   from-scratch **CartPole** physics simulation (`bellman/envs.py`) — the
   real nonlinear pole-balancing equations of motion, semi-implicit Euler
   integrated, no physics library. Because CartPole's state is continuous
   (no table has a cell for it), this needed its own hand-rolled **scalar
   reverse-mode autodiff engine** (`bellman/autodiff.py`) and tiny MLP
   (`bellman/nn.py`) — a `Value` node type with `backward()`, the same
   algorithm every deep learning framework's core is built on, written from
   the chain rule up.

4. **Monte Carlo Exploring Starts on Blackjack** (`bellman/mc.py`), graded
   against an independently-computed optimal policy (`bellman/dp.py`'s
   exact expected-value backward induction over the dealer's outcome
   distribution — deliberately sharing no code with the GridWorld solver).
   Reaches 100% agreement at 500k episodes.

5. **An interactive HTML report** (`bellman/report.py` + `bellman viz`): a
   single self-contained file (no CDN, no build step) with reward-curve
   charts, a scrubbable GridWorld Q-value heatmap with policy arrows, and a
   *live* CartPole balancing animation — a JavaScript mirror of both the
   physics and the trained network's forward pass runs right in the
   browser, no server round trip.

## How to run it

```bash
cd 2026-08-15-bellman

# Individual experiments (each trains for real and prints real numbers)
python3 -m bellman.cli oracle                        # solve GridWorld exactly (DP)
python3 -m bellman.cli gridworld --episodes 500       # Q-Learning / SARSA / SARSA(λ)
python3 -m bellman.cli cartpole --episodes 400        # REINFORCE on CartPole
python3 -m bellman.cli blackjack --episodes 500000    # Monte Carlo Exploring Starts

# Build the interactive report (open viz/report.html in a browser)
python3 -m bellman.cli viz --out viz/report.html

# Everything at once, with a printed summary
python3 -m bellman.cli demo

# Verification
python3 -m unittest discover -s tests -v   # 85 unit/integration tests
bash demo.sh                               # 14 end-to-end checks via the real CLI
```

A pre-built `viz/report.html` is committed in this folder — open it
directly in any browser, no server or install needed.

## Full feature list

**Required (all 4 shipped):**
- Tabular TD control (Q-Learning + SARSA) on a stochastic Cliff-Walking
  GridWorld, with epsilon-greedy exploration and decay.
- Value Iteration + Policy Iteration DP oracle — exact ground truth from
  the true transition model, used to grade every learned GridWorld policy.
- REINFORCE policy-gradient CartPole control, backed by a from-scratch
  scalar autodiff engine + MLP (no autograd library of any kind).
- Interactive self-contained HTML report: reward curves, a scrubbable
  Q-value heatmap + policy-arrow overlay, and a live in-browser CartPole
  animation.

**Stretch (all 3 shipped):**
- Monte Carlo Exploring Starts on Blackjack, graded against an
  independently-derived optimal policy (100% agreement, 500k episodes).
- SARSA(λ) with eligibility traces, trained and charted alongside plain
  Q-Learning/SARSA.
- A full CLI (`oracle / gridworld / cartpole / blackjack / viz / demo`)
  with `argparse`-validated input and clean, non-traceback error messages.

**Verification & polish:**
- 85 unit/integration tests (gradient checks vs. finite differences,
  DP-vs-TD differential checks, an independent Blackjack oracle, a
  headless-browser JS smoke test, and a real cross-process determinism
  test — the one that caught the project's most serious bug).
- Input validation across every CLI flag and library entry point (rejects
  `episodes=0`, degenerate grid dimensions, out-of-range Blackjack states,
  etc. with clear errors instead of silently-wrong output or a traceback).
- A `demo.sh` that exercises every feature through the *real* CLI as
  separate processes and asserts on the actual output — 14/14 green.

## Why this today

Every prior "learning" build in this repo's history has been supervised:
Cotangent backprops an MLP against labeled data, Loom/Sprout train a
transformer to predict the next token — a signal is *given*. Reinforcement
learning is the other half of machine learning, and this repo hadn't
touched it: an agent with no labels at all, only a reward that sometimes
arrives many steps after the decision that earned it (or lost it), facing
the actual credit-assignment problem RL exists to solve. It's also a
genuinely different shape of "agent" than this repo's other agent-shaped
build (Kinesis' evolving creatures, which is population-based and
gradient-free) — here it's one lifelong learner with an explicit value
function, converging toward a fixed point defined by the Bellman equation
itself. And it fits this repo's favorite discipline better than almost any
other domain could: GridWorld is small enough to solve *exactly*, so every
model-free algorithm here has real, provably-correct ground truth to be
checked against — not just "looks plausible."

## Where a human could take this next

- **Deep Q-Networks (DQN)** for a state space too large to tabulate —
  experience replay + a target network are the natural next step once
  function approximation (already built here for CartPole) meets a harder
  environment (Acrobot, LunarLander-style dynamics).
- **Actor-Critic / A2C**, replacing REINFORCE's high-variance Monte-Carlo
  return with a learned value-function baseline — the autodiff engine and
  MLP here already generalize to a second (critic) network with almost no
  new infrastructure.
- **Multi-agent RL**: two GridWorld agents with competing or cooperative
  rewards sharing the same DP-verifiable small-state-space discipline this
  build leans on.
- **A neural network policy for GridWorld** instead of a table, as a direct
  side-by-side against the tabular Q-Learning result already graded here.
- **Prioritized experience replay** or **n-step returns** as a bridge
  between the pure TD (`td.py`) and pure MC (`mc.py`) methods already
  implemented — the classic TD(λ) spectrum, with SARSA(λ) here as one
  concrete point already on that line.
