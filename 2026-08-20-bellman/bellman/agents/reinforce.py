"""REINFORCE: Monte Carlo policy gradient with a learned value baseline.

Unlike Q-learning/DQN (which learn action *values* and act greedily
w.r.t. them), REINFORCE directly parameterizes and optimizes a stochastic
policy pi(a|s): collect a full episode, compute the discounted return
from every timestep, and push up the log-probability of whichever action
was actually taken, weighted by how much better that return was than a
learned baseline V(s) (the "advantage"). The baseline doesn't change
what's optimal — E[baseline term] is exactly zero for any state-only
baseline — it only reduces the variance of the gradient estimate, which
is what makes REINFORCE practical instead of hopelessly noisy.
"""

from __future__ import annotations

import numpy as np

from .nn import MLP, Adam, softmax


class ReinforceAgent:
    def __init__(
        self,
        state_dim,
        n_actions,
        hidden=(64,),
        policy_lr=3e-3,
        value_lr=1e-2,
        gamma=0.99,
        normalize_advantages=True,
        seed=None,
    ):
        self.n_actions = n_actions
        self.gamma = gamma
        self.normalize_advantages = normalize_advantages

        policy_sizes = [state_dim] + list(hidden) + [n_actions]
        value_sizes = [state_dim] + list(hidden) + [1]
        self.policy_net = MLP(policy_sizes, seed=seed)
        self.value_net = MLP(value_sizes, seed=None if seed is None else seed + 1)
        self.policy_opt = Adam(self.policy_net, lr=policy_lr)
        self.value_opt = Adam(self.value_net, lr=value_lr)

        self._rng = np.random.default_rng(seed)

    def action_probs(self, state):
        logits, _ = self.policy_net.forward(np.asarray(state, dtype=np.float64))
        return softmax(logits)

    def select_action(self, state, greedy=False):
        probs = self.action_probs(state)
        if greedy:
            return int(np.argmax(probs))
        return int(self._rng.choice(self.n_actions, p=probs))

    def _discounted_returns(self, rewards):
        returns = np.zeros(len(rewards), dtype=np.float64)
        running = 0.0
        for t in reversed(range(len(rewards))):
            running = rewards[t] + self.gamma * running
            returns[t] = running
        return returns

    def update(self, states, actions, rewards):
        """states: list of state vectors, actions: list of ints,
        rewards: list of floats, all length T (one full episode).
        Returns (policy_loss, value_loss) for logging."""
        states = np.asarray(states, dtype=np.float64)
        actions = np.asarray(actions, dtype=np.int64)
        returns = self._discounted_returns(rewards)

        values, value_cache = self.value_net.forward(states)
        values = values.reshape(-1)
        advantages = returns - values
        if self.normalize_advantages and len(advantages) > 1:
            adv_norm = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        else:
            adv_norm = advantages

        logits, policy_cache = self.policy_net.forward(states)
        probs = softmax(logits)
        onehot = np.zeros_like(probs)
        onehot[np.arange(len(actions)), actions] = 1.0
        d_policy_out = adv_norm[:, None] * (probs - onehot)
        policy_grads = self.policy_net.backward(policy_cache, d_policy_out)
        self.policy_opt.step(policy_grads)

        d_value_out = (values - returns).reshape(-1, 1)
        value_grads = self.value_net.backward(value_cache, d_value_out)
        self.value_opt.step(value_grads)

        policy_loss = float(-np.mean(adv_norm * np.log(np.clip(probs[np.arange(len(actions)), actions], 1e-12, 1.0))))
        value_loss = float(np.mean((values - returns) ** 2))
        return policy_loss, value_loss


def run_episode(env, agent: ReinforceAgent, learn=True, max_steps=500):
    state = env.reset()
    states, actions, rewards = [], [], []
    total_reward = 0.0
    for _ in range(max_steps):
        action = agent.select_action(state, greedy=not learn)
        next_state, reward, done, _ = env.step(action)
        states.append(state)
        actions.append(action)
        rewards.append(reward)
        total_reward += reward
        state = next_state
        if done:
            break
    if learn and states:
        agent.update(states, actions, rewards)
    return total_reward, len(states)


def train(env, agent: ReinforceAgent, n_episodes, max_steps=500):
    returns = []
    for _ in range(n_episodes):
        r, _ = run_episode(env, agent, learn=True, max_steps=max_steps)
        returns.append(r)
    return returns


def evaluate(env, agent: ReinforceAgent, n_episodes, max_steps=500, seeds=None):
    totals = []
    for i in range(n_episodes):
        if seeds is not None:
            env.seed(seeds[i % len(seeds)])
        r, _ = run_episode(env, agent, learn=False, max_steps=max_steps)
        totals.append(r)
    return totals
