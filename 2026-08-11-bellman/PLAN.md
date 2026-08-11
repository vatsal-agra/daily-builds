# Bellman — Reinforcement Learning, From Scratch

## Concept

Every prior build in this repo that "learns" has learned by *supervision*:
nine from-scratch transformers and Cotangent's autodiff engine all fit a
model to labeled targets computed in advance. **Nothing in the repo's
history has learned by *trial and error* against its own consequences** —
an agent that acts, observes a scalar reward, and has to figure out from
that alone which of its past decisions deserved credit. That's
reinforcement learning, and it's a genuinely different learning problem:
there is no dataset, only an environment and a feedback loop.

Bellman is a from-scratch RL library and study: two families of
environments (discrete MDPs with exact solutions, and a continuous-state
control problem with no closed form), three classes of algorithm (dynamic
programming, tabular temporal-difference learning, and function
approximation), and a live browser visualizer to watch policies improve
in real time — not just read a loss number going down.

## Why it's interesting

RL is the one major branch of machine learning this repo hasn't touched,
and it's a good fit for the "verify against ground truth" discipline this
repo has built up: discrete gridworld MDPs have an *exact* optimal policy
computable by value iteration (Bellman optimality equation, solved to a
fixed point) — so tabular Q-learning and SARSA aren't just "look like they
learned," they can be checked bit-for-policy against the provably optimal
answer. CartPole has no such closed form (nonlinear coupled ODE, no
tabular state space), which is exactly why it needs function approximation
and is the harder, more interesting half of the build. Credit assignment
across time (a pole that fell 40 steps ago falling because of an action
taken then, not the action taken just before it fell) is a fundamentally
different problem from anything else shipped here.

## Architecture

```
bellman/
  envs/
    gridworld.py   MDP envs: GridWorld, CliffWalking, WindyGridworld,
                   FrozenLake (stochastic slip). Explicit S, A, P(s'|s,a),
                   R(s,a,s') — real transition/reward functions, not just
                   a step() black box, so the DP oracle can read them.
    cartpole.py    Continuous-state cart-pole: real nonlinear ODE
                   (Barto/Sutton/Anderson 1983 formulation), semi-implicit
                   Euler integration, no gym/pymunk/box2d.
  agents/
    dp.py          Value iteration + policy iteration — the ground-truth
                    oracle every tabular agent is checked against.
    tabular.py     Q-learning, SARSA, every-visit Monte Carlo control.
                   Epsilon-greedy with decay, tabular Q[s][a].
    nn.py          A small purpose-built NN (2-layer MLP): forward pass,
                    hand-derived backward pass, Adam. Not a reuse of
                    Cotangent's generic autodiff engine — built directly
                    for fixed-shape value/policy heads.
    dqn.py         Deep Q-Network: replay buffer, target network,
                    Huber loss, epsilon-greedy — the two tricks (replay +
                    target net) that make TD learning stable with a
                    function approximator instead of a table.
    reinforce.py   Monte-Carlo policy gradient (REINFORCE) with a
                    learned baseline — a fundamentally different update
                    rule (likelihood-ratio gradient of expected return)
                    from DQN's TD bootstrapping.
  viz/
    report.py      Renders a self-contained HTML report: live-replayed
                    episode animations (grid maze walk, cart-pole swing),
                    training-curve charts (reward/episode, epsilon decay,
                    loss), and a Q-value/value-function heatmap over the
                    grid, compared against the DP oracle's true V*.
  cli.py           `bellman train/eval/compare/report` over all envs
                    and agents.
tests/             DP-oracle correctness, env transition-function unit
                    tests, tabular-agent convergence-to-optimal tests,
                    NN gradient checks (finite differences), DQN/REINFORCE
                    end-to-end training tests with numeric pass bars.
demo.sh            Runs the full suite + trains every agent + builds the
                    report, end to end.
```

## Feature list

1. **[required]** From-scratch discrete MDP environments — GridWorld,
   CliffWalking, WindyGridworld, and a stochastic FrozenLake-style
   slippery-ice env — each exposing an explicit transition/reward
   function, plus an exact **value-iteration / policy-iteration oracle**
   that solves the Bellman optimality equation to a fixed point and
   is used as ground truth everywhere else.
2. **[required]** From-scratch tabular TD agents — **Q-learning**,
   **SARSA**, and **every-visit Monte Carlo control** — with
   epsilon-greedy exploration and decay, trained on every gridworld env
   and checked for convergence to the DP oracle's optimal
   value/policy (on-policy vs off-policy divergence on CliffWalking is
   verified explicitly, not just asserted).
3. **[required]** A from-scratch **continuous-state cart-pole physics
   environment** (real nonlinear cart-pole ODE, semi-implicit Euler
   integration) — a genuinely new physics domain for the repo (a single
   controlled dynamical system, not rigid-body collision/contact like
   Tumble/Impulse/Kinesis).
4. **[required]** A from-scratch **Deep Q-Network** (purpose-built 2-layer
   MLP with hand-derived backprop + Adam, experience replay, target
   network, Huber loss) trained to balance the cart-pole for the full
   episode horizon from raw continuous state — no tabular
   discretization.
5. **[stretch]** **REINFORCE** (Monte-Carlo policy-gradient with a
   learned value baseline) as a second, structurally different
   cart-pole algorithm, benchmarked against DQN for sample efficiency.
6. **[stretch]** A self-contained interactive **HTML visualizer** — real-
   time-replayed gameplay (grid-maze walk-through, cart-pole swing
   animation on an HTML canvas), training curves (reward/episode,
   epsilon decay, loss), and a value-function/Q-value heatmap laid over
   the grid next to the DP oracle's true optimum for direct visual
   comparison.

## Verification strategy

- DP oracle checked against hand-solved tiny MDPs (2x2, deterministic
  3-state chain) with a known closed-form answer.
- Tabular agents checked for **exact convergence** (matching greedy
  policy, value within a numeric tolerance) to the DP oracle on every
  gridworld env across multiple seeds.
- NN backward pass checked against central-difference numerical
  gradients on every parameter.
- DQN/REINFORCE checked with a hard numeric pass bar: mean reward over
  the last N evaluation episodes at/near the environment's maximum
  (cart-pole's step cap), not "trained for X steps and looked fine."
