"""Tabular Q-learning (off-policy TD control) and SARSA (on-policy TD
control). Both share the same epsilon-greedy action selection and the
same update loop shape — a Q-table indexed by (state, action) updated
towards a bootstrapped target — and differ in exactly one place: how the
target for the *next* state is computed. That single difference is what
produces the famous Cliff Walking divergence (see envs/gridworld.py's
make_cliff_walking and tests/test_qlearning.py's differential test).
"""

from __future__ import annotations

import random


class TDAgent:
    """Shared scaffold for tabular TD-control agents."""

    def __init__(
        self,
        n_states,
        n_actions,
        alpha=0.5,
        gamma=0.99,
        epsilon=1.0,
        epsilon_decay=0.999,
        epsilon_min=0.01,
        seed=None,
    ):
        self.n_states = n_states
        self.n_actions = n_actions
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        self._rng = random.Random(seed)
        self.Q = [[0.0] * n_actions for _ in range(n_states)]

    def select_action(self, state, greedy=False):
        if (not greedy) and self._rng.random() < self.epsilon:
            return self._rng.randrange(self.n_actions)
        return self._argmax(state)

    def _argmax(self, state):
        row = self.Q[state]
        best_a, best_v = 0, row[0]
        for a in range(1, self.n_actions):
            if row[a] > best_v:
                best_a, best_v = a, row[a]
        return best_a

    def greedy_policy(self):
        return [self._argmax(s) for s in range(self.n_states)]

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def _target_value(self, next_state, next_action, done):
        raise NotImplementedError

    def update(self, state, action, reward, next_state, next_action, done):
        target = reward
        if not done:
            target += self.gamma * self._target_value(next_state, next_action, done)
        td_error = target - self.Q[state][action]
        self.Q[state][action] += self.alpha * td_error
        return td_error


class QLearningAgent(TDAgent):
    """Off-policy: bootstraps from max_a' Q(s', a') regardless of which
    action the behavior policy actually takes next."""

    def _target_value(self, next_state, next_action, done):
        return max(self.Q[next_state])


class SarsaAgent(TDAgent):
    """On-policy: bootstraps from Q(s', a') where a' is the action the
    agent's own (epsilon-greedy) policy actually selected — so the update
    accounts for the exploratory policy's own chance of a bad outcome."""

    def _target_value(self, next_state, next_action, done):
        return self.Q[next_state][next_action]


def run_episode(env, agent, learn=True, max_steps=None):
    """Runs one full episode. For SARSA this must select next_action
    *before* calling update() (true on-policy: the action actually taken
    is what gets bootstrapped from); Q-learning ignores next_action.
    Returns (total_reward, n_steps).
    """
    state = env.reset()
    action = agent.select_action(state, greedy=not learn)
    total_reward = 0.0
    steps = 0
    done = False
    while not done:
        next_state, reward, done, info = env.step(action)
        next_action = agent.select_action(next_state, greedy=not learn)
        if learn:
            agent.update(state, action, reward, next_state, next_action, done)
        total_reward += reward
        steps += 1
        state, action = next_state, next_action
        if max_steps is not None and steps >= max_steps:
            break
    if learn:
        agent.decay_epsilon()
    return total_reward, steps


def train(env, agent, n_episodes, max_steps=None):
    """Trains for n_episodes, returning the list of per-episode returns."""
    returns = []
    for _ in range(n_episodes):
        r, _ = run_episode(env, agent, learn=True, max_steps=max_steps)
        returns.append(r)
    return returns
