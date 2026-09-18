# Bellman — a from-scratch reinforcement learning laboratory

## Concept

Every prior build in this repo that "learns" has been supervised: nine
from-scratch Transformers (Loom) trained on a fixed corpus of correct
answers, Cotangent's scalar-autodiff MLP fit to a labeled dataset, Unify's
type inferencer derives a static answer that either checks or doesn't.
Kinesis got the closest to trial-and-error with its genetic algorithm, but
a GA is population-based search over a fitness landscape — there is no
agent, no state, no notion of *delayed* credit assignment.

Reinforcement learning is a different animal: an agent acts in an
environment it does not have a labeled answer for, receives a scalar
reward that may arrive many steps after the decision that earned it, and
has to learn a policy purely from that trial-and-error signal — balancing
exploration (try something new) against exploitation (do what has worked).
The mathematical spine is the Bellman equation: the value of a state is
the immediate reward plus the discounted value of wherever you land next.
Every algorithm here — dynamic programming, Monte-Carlo-flavored TD
control, policy gradients — is a different way of exploiting that one
recursive identity, and the project name is the hook they all hang on.

It is also an unusually well-verified domain to build in: value iteration
over a known MDP produces a *provably optimal* value function (Bellman
optimality is a contraction mapping — it has a unique fixed point), so
every learned policy has a ground-truth oracle to be checked against,
not just "looks plausible." The classic Cliff Walking task additionally
has a famous, well-documented qualitative result (Sutton & Barto §6.5):
on-policy SARSA and off-policy Q-learning converge to *different* optimal
policies on the exact same MDP — Q-learning learns the risky shortest path
along the cliff edge, SARSA learns the longer safe path because on-policy
learning accounts for the exploratory ε-greedy policy's own risk of
stepping off the edge. Reproducing that named, textbook result on purpose
is a strong correctness signal no amount of "it ran without crashing" can
fake.

## Architecture

```
bellman/
  envs/
    cliffwalking.py   # 4x12 gridworld MDP: explicit P(s'|s,a), R(s,a,s')
    tictactoe.py       # 2-player MDP, terminal win/draw/loss reward
  dp.py                 # Policy Iteration + Value Iteration -> V*, Q*, pi*
  td.py                 # tabular SARSA (on-policy) + Q-learning (off-policy)
  minimax.py            # memoized negamax perfect tic-tac-toe oracle
  selfplay.py           # TD(0) self-play control for tic-tac-toe
  reinforce.py           # REINFORCE policy gradient, hand-rolled softmax net
  viz_export.py          # runs every algorithm, writes JSON for the viewer
visualizer/
  index.html              # self-contained viewer: value heatmaps, policy
                           # arrows, trajectory replay, training curves,
                           # play-vs-agent tic-tac-toe board
tests/
  test_dp.py, test_td.py, test_selfplay.py, test_reinforce.py
demo.sh                    # runs everything end-to-end, prints PASS/FAIL
```

Everything is pure Python 3 standard library — no numpy, no gym, no RL or
ML framework of any kind. "From scratch" here means the MDPs, the Bellman
backup, the TD updates, the eligibility of exploration, and the tiny
policy network's forward/backward pass are all hand-written.

## Feature list

1. **(required) Cliff Walking MDP + Dynamic Programming oracle.** The
   classic 4x12 gridworld (start bottom-left, goal bottom-right, a row of
   cliff cells between them worth -100 and an instant reset) implemented
   as an explicit MDP with deterministic transitions and a -1 per-step
   reward, solved exactly by Policy Iteration and Value Iteration. Both
   converge to the identical optimal value function (cross-checked against
   each other), which becomes the ground-truth oracle for everything else.

2. **(required) Tabular TD control: SARSA vs Q-learning on Cliff Walking.**
   Both algorithms trained with ε-greedy exploration and a decaying
   learning rate until their greedy policies stop changing. Verified two
   ways: (a) each learned policy's exact expected return, computed by
   policy evaluation against the real MDP, must be close to the DP oracle's
   optimum; (b) the textbook qualitative split must reproduce — Q-learning's
   greedy path must hug the cliff edge (shorter, riskier) while SARSA's
   must take the safe top row (longer), and this is asserted programmatically,
   not just eyeballed from a picture.

3. **(required) Perfect-play oracle + TD(0) self-play for Tic-Tac-Toe.**
   A from-scratch memoized negamax solver that plays provably optimal
   Tic-Tac-Toe (the game is a solved draw with correct play). A separate
   TD(0) value-function agent trains purely by playing itself for
   thousands of games with no minimax knowledge injected, then is
   validated by playing hundreds of games against the minimax oracle as
   both X and O: a correctly trained agent must never lose.

4. **(required) Value/policy visual artifacts + training-curve verification.**
   `viz_export.py` runs every trained algorithm and serializes value
   grids, greedy policy arrows, a full cliff-edge trajectory per
   algorithm, and per-episode return curves for SARSA/Q-learning/self-play
   into JSON, consumed by a real interactive HTML/Canvas/SVG viewer (value
   heatmap, policy-arrow overlay, trajectory playback scrubber, training
   curve chart, and a play-against-the-trained-agent Tic-Tac-Toe board) —
   not a static screenshot, an artifact a human can actually explore.

5. **(stretch) REINFORCE policy gradient on a continuous-state task.** A
   hand-rolled 2-layer softmax policy network (manual forward pass,
   manual backprop, no autodiff engine borrowed from any earlier build)
   trained with the REINFORCE (Monte Carlo policy gradient) algorithm on
   a discretized Mountain-Car-style "push the underpowered cart up the
   hill" task with continuous position/velocity state — a genuinely
   different learning signal (whole-episode return, no bootstrapped
   value function) from the TD methods in features 2-3.

6. **(stretch) SARSA(λ) eligibility traces.** Extend the TD control code
   with a backward-view eligibility-trace variant and show it reaches the
   Cliff Walking optimum in measurably fewer episodes than 1-step SARSA
   at matched hyperparameters, demonstrating the credit-assignment speedup
   eligibility traces are famous for.

Required features are 1-4. Stretch features are 5-6; at least one (5) is
implemented fully in Phase 4.
