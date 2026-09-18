"""REINFORCE (Williams 1992): Monte Carlo policy gradient, applied to
CartPole through a small hand-rolled 2-layer softmax policy network.

This is a genuinely different learning signal from bellman/td.py's SARSA
and Q-learning: those bootstrap off a one-step TD target (the current
estimate of the *next* state's value) and can update mid-episode.
REINFORCE never bootstraps -- it waits for a complete episode, computes
the actual (discounted) return-to-go from every visited state, and pushes
the policy's log-probability of each action taken up or down in direct
proportion to how much better or worse that return was than a baseline.
There is also no Q-table here at all (CartPole's state is a continuous
4-vector), so "the policy" is entirely encoded in the weights of a tiny
neural network this module trains from raw gradients it derives and
backpropagates by hand -- no autodiff engine of any kind, borrowed or
otherwise.

Network: state (4, normalized) -> Linear -> tanh -> Linear -> softmax
over 2 actions. The backward pass exploits the standard identity
d(log softmax(logits)[a]) / d(logits) = onehot(a) - probs, then chains
back through tanh and the two linear layers by hand. bellman/gradcheck.py
verifies this against numerical finite differences before it's trusted
for training, same discipline this repo's from-scratch Transformer builds
(Loom, various dates) apply to their own hand-derived backward passes.

Earlier draft of this module used Mountain Car instead. That environment
is physically correct (a hand-coded "push in the direction of current
velocity" heuristic solves it in ~120 steps every time) but its reward is
-1 per tick with *no* other signal, and a uniformly random policy gets 0
successes in 3000 tries within a reasonable step budget -- verified
directly, not assumed. Vanilla REINFORCE never saw a single success to
learn from, and every fix attempted (potential-based and dense reward
shaping, action-repeat/frame-skip, per-timestep baselines, entropy
bonuses -- all still in this file's git history) either didn't help or
introduced a new failure mode, most notably a real divergence bug this
process caught by directly inspecting weight norms mid-training (see
REVIEW.md). Mountain Car's sparse-reward hard-exploration property is
genuinely famous in the RL literature for defeating vanilla policy
gradient without much more machinery (actor-critic, or far more
compute) than a from-scratch pure-Python stretch feature can spend here.
CartPole is the standard first benchmark for policy-gradient methods for
exactly the opposite reason: reward is dense (+1 every tick survived), so
every single timestep already carries a usable gradient signal and there
is no hard exploration wall to cross first. Swapping the task, not the
algorithm, was the right fix -- documented in REVIEW.md rather than
silently done.
"""
import math
import random

from .envs.cartpole import CartPole


def _tanh(x):
    return math.tanh(x)


def softmax(logits):
    m = max(logits)
    exps = [math.exp(v - m) for v in logits]
    total = sum(exps)
    return [v / total for v in exps]


class PolicyNet:
    def __init__(self, input_size, hidden_size, output_size, seed=0):
        rng = random.Random(seed)
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = output_size
        s1 = 1.0 / math.sqrt(input_size)
        s2 = 1.0 / math.sqrt(hidden_size)
        self.W1 = [[rng.uniform(-s1, s1) for _ in range(input_size)] for _ in range(hidden_size)]
        self.b1 = [0.0] * hidden_size
        self.W2 = [[rng.uniform(-s2, s2) for _ in range(hidden_size)] for _ in range(output_size)]
        self.b2 = [0.0] * output_size

    def forward(self, x):
        h_pre = [
            sum(self.W1[i][j] * x[j] for j in range(self.input_size)) + self.b1[i]
            for i in range(self.hidden_size)
        ]
        h = [_tanh(v) for v in h_pre]
        logits = [
            sum(self.W2[k][i] * h[i] for i in range(self.hidden_size)) + self.b2[k]
            for k in range(self.output_size)
        ]
        probs = softmax(logits)
        return probs, {"x": x, "h": h, "probs": probs}

    def backward(self, cache, action, advantage):
        """Gradient of `advantage * log probs[action]` w.r.t. every
        parameter, for gradient ASCENT (callers add lr * grad, they do
        not subtract it)."""
        x, h, probs = cache["x"], cache["h"], cache["probs"]
        dlogits = [
            ((1.0 if k == action else 0.0) - probs[k]) * advantage
            for k in range(self.output_size)
        ]
        dW2 = [[dlogits[k] * h[i] for i in range(self.hidden_size)] for k in range(self.output_size)]
        db2 = list(dlogits)
        dh = [
            sum(self.W2[k][i] * dlogits[k] for k in range(self.output_size))
            for i in range(self.hidden_size)
        ]
        dh_pre = [dh[i] * (1.0 - h[i] * h[i]) for i in range(self.hidden_size)]
        dW1 = [[dh_pre[i] * x[j] for j in range(self.input_size)] for i in range(self.hidden_size)]
        db1 = list(dh_pre)
        return {"dW1": dW1, "db1": db1, "dW2": dW2, "db2": db2}

    def apply_grads(self, grads, lr):
        for i in range(self.hidden_size):
            for j in range(self.input_size):
                self.W1[i][j] += lr * grads["dW1"][i][j]
            self.b1[i] += lr * grads["db1"][i]
        for k in range(self.output_size):
            for i in range(self.hidden_size):
                self.W2[k][i] += lr * grads["dW2"][k][i]
            self.b2[k] += lr * grads["db2"][k]

    def sample_action(self, x, rng):
        probs, cache = self.forward(x)
        r = rng.random()
        cum = 0.0
        for a, p in enumerate(probs):
            cum += p
            if r <= cum:
                return a, cache
        return self.output_size - 1, cache  # float rounding fallback

    def greedy_action(self, x):
        probs, _ = self.forward(x)
        return max(range(len(probs)), key=lambda a: probs[a])


def run_episode(env, net, rng, greedy=False):
    state = env.reset(rng)
    trajectory = []
    done = False
    survived_full_episode = False
    while not done:
        norm = env.normalize(state)
        if greedy:
            action = net.greedy_action(norm)
            cache = None
        else:
            action, cache = net.sample_action(norm, rng)
        state, reward, done, survived_full_episode = env.step(state, action)
        trajectory.append({"cache": cache, "action": action, "reward": reward})
    return trajectory, survived_full_episode


def reinforce_train(env=None, episodes=5000, hidden_size=16, lr=0.02, gamma=0.99, seed=0,
                     batch_size=10, eval_every=250, eval_episodes=20):
    """Train a PolicyNet with REINFORCE: whole-episode return-to-go,
    batched advantage normalization, and one gradient step per batch.
    Returns (net, per-episode returns, per-episode "survived the full
    episode" flags, greedy-eval checkpoints) -- the first three have one
    entry per episode regardless of batching; checkpoints has one entry
    every `eval_every` episodes.

    Updating after every *single* episode (tried first) was unstable:
    CartPole's episode lengths swing wildly (a lucky early episode can
    survive 10x longer than an unlucky one), so a single episode's own
    mean/std return-to-go is itself a noisy, high-variance estimate, and
    a big step taken on a noisy estimate can undo several episodes' worth
    of progress in one shot -- observed directly (avg return climbing
    past 140 then collapsing back under 20 within a few hundred episodes,
    repeatedly). Pooling `batch_size` episodes' return-to-go values before
    normalizing (and averaging their gradients into one update) trades a
    slightly staler policy for a much less noisy advantage estimate,
    which in practice is what actually converges instead of oscillating
    (see REVIEW.md for the side-by-side numbers).

    The raw per-episode `returns` stay noisy even late in training and
    substantially understate how good the policy has actually gotten --
    they're the *exploring* (epsilon-soft-via-softmax) policy's returns,
    not the confident greedy one evaluate() reports on, and a policy that
    has essentially converged to "always do the right thing" still falls
    quickly whenever its own sampling picks the wrong action at a
    sensitive moment. `checkpoints` (periodic *greedy* mini-evaluations
    using a separate, fixed evaluation seed so they don't perturb
    training) is what actually shows the real learning curve; see
    viz_export.py's chart for the visible gap between the two.
    """
    if env is None:
        env = CartPole()
    rng = random.Random(seed)
    net = PolicyNet(input_size=4, hidden_size=hidden_size, output_size=env.n_actions, seed=seed)
    returns = []
    survived_flags = []
    checkpoints = []

    n_batches = (episodes + batch_size - 1) // batch_size
    for batch_idx in range(n_batches):
        batch_trajectories = []
        batch_returns_to_go = []

        for _ in range(min(batch_size, episodes - len(returns))):
            trajectory, survived = run_episode(env, net, rng, greedy=False)
            total_return = sum(step["reward"] for step in trajectory)
            returns.append(total_return)
            survived_flags.append(survived)

            G = 0.0
            returns_to_go = [0.0] * len(trajectory)
            for t in range(len(trajectory) - 1, -1, -1):
                G = trajectory[t]["reward"] + gamma * G
                returns_to_go[t] = G

            batch_trajectories.append(trajectory)
            batch_returns_to_go.append(returns_to_go)

        pooled = [g for rtg in batch_returns_to_go for g in rtg]
        mean_g = sum(pooled) / len(pooled)
        var_g = sum((g - mean_g) ** 2 for g in pooled) / len(pooled)
        std_g = math.sqrt(var_g) + 1e-6

        accum = None
        n_steps = 0
        for trajectory, returns_to_go in zip(batch_trajectories, batch_returns_to_go):
            for t, step in enumerate(trajectory):
                advantage = (returns_to_go[t] - mean_g) / std_g
                grads = net.backward(step["cache"], step["action"], advantage)
                accum = grads if accum is None else _add_grads(accum, grads)
                n_steps += 1

        net.apply_grads(_scale_grads(accum, 1.0 / n_steps), lr)

        if eval_every and len(returns) // eval_every > (len(returns) - len(batch_trajectories)) // eval_every:
            eval_stats = evaluate(env, net, eval_episodes, seed=1_000_000 + batch_idx)
            checkpoints.append({"episode": len(returns), **eval_stats})

    return net, returns, survived_flags, checkpoints


def _add_grads(a, b):
    return {
        key: [[x + y for x, y in zip(rowa, rowb)] for rowa, rowb in zip(a[key], b[key])]
        if isinstance(a[key][0], list)
        else [x + y for x, y in zip(a[key], b[key])]
        for key in a
    }


def _scale_grads(grads, factor):
    return {
        key: [[x * factor for x in row] for row in grads[key]]
        if isinstance(grads[key][0], list)
        else [x * factor for x in grads[key]]
        for key in grads
    }


def evaluate(env, net, episodes, seed):
    rng = random.Random(seed)
    successes = 0
    steps = []
    for _ in range(episodes):
        trajectory, survived = run_episode(env, net, rng, greedy=True)
        if survived:
            successes += 1
        steps.append(len(trajectory))
    return {
        "episodes": episodes,
        "successes": successes,
        "success_rate": successes / episodes,
        "avg_steps": sum(steps) / len(steps),
        "min_steps": min(steps),
    }
