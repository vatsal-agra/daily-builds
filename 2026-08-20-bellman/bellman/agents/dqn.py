"""Deep Q-Network: a neural Q-function trained with the two tricks that
make bootstrapped function approximation stable — an experience replay
buffer (breaks the correlation between consecutive samples and reuses
data) and a target network (holds the bootstrap target still for a while
instead of chasing a value that moves every single gradient step).

Both tricks are togglable (`use_replay`, `use_target_network`) so
train.py's `ablation` command can demonstrate, not just assert, why they
matter — see REVIEW.md / README.md for the measured result.
"""

from __future__ import annotations

import random

import numpy as np

from .nn import MLP, Adam


class ReplayBuffer:
    """A fixed-capacity ring buffer. Backed by a plain list with a
    circular write pointer rather than `collections.deque`: deques don't
    support O(1) random-access indexing, so `random.sample()` directly on
    one degrades towards O(capacity) per draw as the buffer fills —
    exactly the kind of "technically correct, quietly quadratic" bug this
    project's adversarial-review phase is meant to catch. Indexing into a
    list is O(1), so sampling stays O(batch_size) regardless of capacity.
    """

    def __init__(self, capacity, seed=None):
        self.capacity = capacity
        self.buf = []
        self._next = 0
        self._rng = random.Random(seed)
        self.last = None  # the most recently pushed transition, O(1) to fetch
        # even after the ring buffer has wrapped and buf[-1] no longer
        # means "most recent" (it means "whatever last occupied that slot").

    def push(self, state, action, reward, next_state, done):
        item = (state, action, reward, next_state, done)
        if len(self.buf) < self.capacity:
            self.buf.append(item)
        else:
            self.buf[self._next] = item
        self._next = (self._next + 1) % self.capacity
        self.last = item

    def __len__(self):
        return len(self.buf)

    def sample(self, batch_size):
        idx = self._rng.sample(range(len(self.buf)), batch_size)
        batch = [self.buf[i] for i in idx]
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states, dtype=np.float64),
            np.array(actions, dtype=np.int64),
            np.array(rewards, dtype=np.float64),
            np.array(next_states, dtype=np.float64),
            np.array(dones, dtype=np.float64),
        )


class DQNAgent:
    def __init__(
        self,
        state_dim,
        n_actions,
        hidden=(64, 64),
        lr=1e-3,
        gamma=0.99,
        epsilon=1.0,
        epsilon_decay=0.995,
        epsilon_min=0.05,
        buffer_capacity=50_000,
        batch_size=64,
        target_update_freq=200,
        use_replay=True,
        use_target_network=True,
        seed=None,
    ):
        sizes = [state_dim] + list(hidden) + [n_actions]
        self.n_actions = n_actions
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq
        self.use_replay = use_replay
        self.use_target_network = use_target_network

        self.q_net = MLP(sizes, seed=seed)
        self.optimizer = Adam(self.q_net, lr=lr)
        if use_target_network:
            self.target_net = MLP(sizes, seed=seed)
            self.target_net.set_params_like(self.q_net)
        else:
            # No target network: bootstrap directly off the online network
            # that is changing every step. This is the unstable ablation.
            self.target_net = self.q_net

        self.replay = ReplayBuffer(buffer_capacity, seed=seed)
        self._rng = random.Random(seed)
        self._n_updates = 0
        self.last_loss = None

    def select_action(self, state, greedy=False):
        if (not greedy) and self._rng.random() < self.epsilon:
            return self._rng.randrange(self.n_actions)
        q, _ = self.q_net.forward(np.asarray(state, dtype=np.float64))
        return int(np.argmax(q))

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def observe(self, state, action, reward, next_state, done):
        self.replay.push(state, action, reward, next_state, done)

    def train_step(self):
        """One gradient step. Returns the batch MSE TD loss, or None if
        there isn't enough data yet."""
        if self.use_replay:
            if len(self.replay) < self.batch_size:
                return None
            states, actions, rewards, next_states, dones = self.replay.sample(
                self.batch_size
            )
        else:
            # No replay: train only on the single most recent transition —
            # exactly what naive online TD-with-a-neural-net looks like.
            if self.replay.last is None:
                return None
            s, a, r, s2, d = self.replay.last
            states = np.array([s], dtype=np.float64)
            actions = np.array([a], dtype=np.int64)
            rewards = np.array([r], dtype=np.float64)
            next_states = np.array([s2], dtype=np.float64)
            dones = np.array([d], dtype=np.float64)

        q_pred, cache = self.q_net.forward(states)
        batch_idx = np.arange(len(actions))
        q_taken = q_pred[batch_idx, actions]

        next_q, _ = self.target_net.forward(next_states)
        next_max = next_q.max(axis=1)
        targets = rewards + self.gamma * next_max * (1.0 - dones)

        d_out = np.zeros_like(q_pred)
        d_out[batch_idx, actions] = q_taken - targets

        grads = self.q_net.backward(cache, d_out)
        self.optimizer.step(grads)

        self._n_updates += 1
        if self.use_target_network and self._n_updates % self.target_update_freq == 0:
            self.target_net.set_params_like(self.q_net)

        loss = float(np.mean((q_taken - targets) ** 2))
        self.last_loss = loss
        return loss


def train(env, agent: DQNAgent, n_episodes, max_steps=500, train_every=1):
    """Trains DQN for n_episodes on env. Returns (returns, losses) —
    per-episode total reward and the mean training loss for that
    episode (None for episodes where no gradient step ran yet)."""
    returns = []
    losses = []
    step_count = 0
    for _ in range(n_episodes):
        state = env.reset()
        total_reward = 0.0
        ep_losses = []
        for _ in range(max_steps):
            action = agent.select_action(state)
            next_state, reward, done, info = env.step(action)
            agent.observe(state, action, reward, next_state, float(done and not info.get("truncated", False)))
            state = next_state
            total_reward += reward
            step_count += 1
            if step_count % train_every == 0:
                loss = agent.train_step()
                if loss is not None:
                    ep_losses.append(loss)
            if done:
                break
        agent.decay_epsilon()
        returns.append(total_reward)
        losses.append(sum(ep_losses) / len(ep_losses) if ep_losses else None)
    return returns, losses


def evaluate(env, agent: DQNAgent, n_episodes, max_steps=500, seeds=None):
    """Runs greedy (epsilon=0) evaluation episodes, optionally over a
    fixed list of env seeds so results aren't cherry-picked."""
    totals = []
    for i in range(n_episodes):
        if seeds is not None:
            env.seed(seeds[i % len(seeds)])
        state = env.reset()
        total = 0.0
        for _ in range(max_steps):
            action = agent.select_action(state, greedy=True)
            state, reward, done, _ = env.step(action)
            total += reward
            if done:
                break
        totals.append(total)
    return totals
