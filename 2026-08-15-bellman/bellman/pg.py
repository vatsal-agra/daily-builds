"""REINFORCE: Monte-Carlo policy gradient (Williams 1992) with a mean-return
baseline for variance reduction, driving a small MLP policy over CartPole's
continuous 4D state -- a table has no cells for `(x, x_dot, theta,
theta_dot)`, so this is where the from-scratch autodiff engine (`autodiff.py`)
and MLP (`nn.py`) earn their place: the policy IS a computation graph, and
"training" IS calling `.backward()` on the sampled trajectory's log-likelihood.

The gradient estimator, for a single episode with discounted returns G_t:
    grad_theta J = E[ sum_t  grad_theta log pi_theta(a_t | s_t) * (G_t - b) ]
`b` is the mean return over the episode, a simple but effective baseline
that doesn't bias the gradient (its expectation over actions is zero) while
cutting variance substantially.
"""
import random

from .autodiff import Value, softmax
from .nn import MLP


class ReinforceAgent:
    def __init__(self, obs_dim, n_actions, hidden=8, lr=0.02, gamma=0.99, seed=0):
        self.policy = MLP([obs_dim, hidden, n_actions], seed=seed)
        self.n_actions = n_actions
        self.lr = lr
        self.gamma = gamma
        self.rng = random.Random(seed + 1)

    def act(self, state):
        """Sample an action from the current policy; returns (action, log_prob Value)."""
        logits = self.policy([Value(x) for x in state])
        probs = softmax(logits)
        weights = [p.data for p in probs]
        # guard against tiny numerical drift so random.choices never sees negatives
        weights = [max(w, 0.0) for w in weights]
        action = self.rng.choices(range(self.n_actions), weights=weights, k=1)[0]
        return action, probs[action].log()

    def act_greedy(self, state):
        """Deterministic argmax action -- used for held-out evaluation."""
        logits = self.policy([Value(x) for x in state])
        return max(range(self.n_actions), key=lambda i: logits[i].data)

    def update(self, log_probs, rewards):
        """One REINFORCE gradient step from a single completed episode."""
        returns = []
        G = 0.0
        for r in reversed(rewards):
            G = r + self.gamma * G
            returns.append(G)
        returns.reverse()

        baseline = sum(returns) / len(returns)
        advantages = [g - baseline for g in returns]

        loss = Value(0.0)
        for log_p, adv in zip(log_probs, advantages):
            loss = loss + (-log_p * adv)
        loss = loss / len(log_probs)

        self.policy.zero_grad()
        loss.backward()
        for p in self.policy.parameters():
            p.data -= self.lr * p.grad

        return sum(rewards)


def train_reinforce(env, episodes=400, hidden=8, lr=0.02, gamma=0.99,
                     max_steps=300, seed=0, log_every=25, callback=None):
    agent = ReinforceAgent(obs_dim=4, n_actions=2, hidden=hidden, lr=lr, gamma=gamma, seed=seed)
    episode_returns = []

    for ep in range(episodes):
        state = env.reset()
        log_probs, rewards = [], []
        for _ in range(max_steps):
            action, log_p = agent.act(state)
            state, r, done, _ = env.step(action)
            log_probs.append(log_p)
            rewards.append(r)
            if done:
                break
        total = agent.update(log_probs, rewards)
        episode_returns.append(total)
        if callback is not None:
            callback(ep, total)

    return agent, episode_returns


def evaluate(env, agent, episodes=50, max_steps=500, greedy=True):
    totals = []
    for _ in range(episodes):
        state = env.reset()
        total = 0.0
        for _ in range(max_steps):
            action = agent.act_greedy(state) if greedy else agent.act(state)[0]
            state, r, done, _ = env.step(action)
            total += r
            if done:
                break
        totals.append(total)
    return totals
