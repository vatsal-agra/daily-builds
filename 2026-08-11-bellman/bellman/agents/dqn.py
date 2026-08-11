"""Deep Q-Network: TD control with a function approximator instead of a
table.

Plain tabular Q-learning (bellman.agents.tabular) can't touch cart-pole:
the state is four continuous numbers, so there is no finite table to
fill in. Swapping the table for a neural net breaks TD learning's
convergence guarantees on its own though -- consecutive transitions are
correlated, and bootstrapping off a target that moves every gradient step
chases its own tail. DQN (Mnih et al. 2015) fixes both with two specific
mechanisms, both implemented here:

  * experience replay -- a buffer of past transitions, sampled uniformly
    at random for each minibatch, so gradient steps aren't dominated by
    whatever the agent is doing *right now*.
  * a target network -- a periodically-synced copy of the Q-network used
    only to compute TD targets, so the target doesn't shift on every
    single gradient step the online network takes.

Two further, standard refinements are used, both documented in
REVIEW.md's adversarial pass as things the first, plainer implementation
was missing:

  * Double DQN (van Hasselt et al. 2015) -- the online network picks the
    greedy next action, the target network only evaluates it. Vanilla DQN
    uses max_a' Q_target(s',a') for both, which systematically
    overestimates value whenever Q_target is noisy (Jensen's inequality
    applied to a max), and that overestimation compounds through
    bootstrapping. Decoupling "which action is best" from "how good is
    it" removes that bias.
  * fixed-scale state normalization -- cart-pole's four state components
    live on very different scales (position in +-2.4, angle in +-0.21
    radians); feeding them raw to a freshly-initialized net means the
    gradient is dominated by whichever component happens to be numerically
    largest. Dividing by each component's known operating range keeps
    every input O(1).

Huber loss (smooth L1) is used instead of MSE so a single wildly-wrong
target (which happens constantly early in training) can't blow up the
gradient.
"""
import random
from collections import deque

from .nn import MLP, Adam

# cart-pole's own termination thresholds / typical operating ranges
# (bellman.envs.cartpole.X_THRESHOLD etc.) -- not tuned to this task,
# just the physical bounds the env already defines
DEFAULT_STATE_SCALE = (2.4, 3.0, 0.21, 3.0)


class ReplayBuffer:
    def __init__(self, capacity=20_000, seed=0):
        self.buf = deque(maxlen=capacity)
        self.rng = random.Random(seed)

    def push(self, s, a, r, ns, done):
        self.buf.append((s, a, r, ns, done))

    def sample(self, batch_size):
        return self.rng.sample(self.buf, batch_size)

    def __len__(self):
        return len(self.buf)


def _huber_grad(pred, target, delta=1.0):
    err = pred - target
    if abs(err) <= delta:
        return err
    return delta if err > 0 else -delta


class DQNAgent:
    def __init__(
        self,
        state_dim,
        n_actions,
        hidden=48,
        gamma=0.995,
        lr=3e-3,
        buffer_size=20_000,
        batch_size=48,
        train_start=300,
        target_update_every=150,
        state_scale=None,
        seed=0,
    ):
        self.n_actions = n_actions
        self.gamma = gamma
        self.batch_size = batch_size
        self.train_start = train_start
        self.target_update_every = target_update_every
        self.state_scale = list(state_scale) if state_scale else [1.0] * state_dim

        self.q_net = MLP([state_dim, hidden, hidden, n_actions], seed=seed)
        self.target_net = self.q_net.clone()
        self.optimizer = Adam(self.q_net, lr=lr)
        self.buffer = ReplayBuffer(buffer_size, seed=seed)
        self.rng = random.Random(seed + 1)

        self._steps = 0
        self.last_loss = None

    def _norm(self, state):
        return [state[i] / self.state_scale[i] for i in range(len(state))]

    def act(self, state, epsilon):
        if self.rng.random() < epsilon:
            return self.rng.randrange(self.n_actions)
        q = self.q_net.forward(self._norm(state))
        return max(range(self.n_actions), key=lambda a: q[a])

    def observe(self, s, a, r, ns, done):
        self.buffer.push(list(s), a, r, list(ns), done)

    def _zero_grads_like(self):
        return [([[0.0] * layer.n_in for _ in range(layer.n_out)], [0.0] * layer.n_out)
                for layer in self.q_net.layers]

    def learn(self):
        """One minibatch gradient step, if the buffer has enough data.
        Returns the average Huber loss for this batch, or None if it
        skipped (buffer still warming up)."""
        if len(self.buffer) < max(self.train_start, self.batch_size):
            return None
        self._steps += 1

        batch = self.buffer.sample(self.batch_size)
        grads_sum = self._zero_grads_like()
        total_loss = 0.0

        for s, a, r, ns, done in batch:
            ns_n = self._norm(ns)
            # Double DQN target: online net selects the greedy action,
            # target net supplies that action's value
            online_next = self.q_net.forward(ns_n)
            a_star = max(range(self.n_actions), key=lambda x: online_next[x])
            target_next = self.target_net.forward(ns_n)
            y = r if done else r + self.gamma * target_next[a_star]

            s_n = self._norm(s)
            q_pred = self.q_net.forward(s_n)
            pred = q_pred[a]
            g = _huber_grad(pred, y)
            err = pred - y
            total_loss += 0.5 * err * err if abs(err) <= 1.0 else (abs(err) - 0.5)

            d_out = [0.0] * self.n_actions
            d_out[a] = g
            grads = self.q_net.backward(d_out)
            for (dW_sum, db_sum), (dW, db) in zip(grads_sum, grads):
                for o in range(len(dW)):
                    row_sum, row = dW_sum[o], dW[o]
                    for i in range(len(row)):
                        row_sum[i] += row[i]
                    db_sum[o] += db[o]

        n = len(batch)
        avg_grads = [
            ([[v / n for v in row] for row in dW], [v / n for v in db])
            for dW, db in grads_sum
        ]
        self.optimizer.step(self.q_net, avg_grads)

        if self._steps % self.target_update_every == 0:
            self.target_net.load_from(self.q_net)

        self.last_loss = total_loss / n
        return self.last_loss


def train(env, agent=None, episodes=300, epsilon_start=1.0, epsilon_end=0.03,
          epsilon_decay_episodes=200, max_steps=500, seed=0, train_every=3,
          on_episode=None):
    """Trains a DQNAgent on env (must expose reset()/step() like
    CartPoleEnv). Returns (agent, episode_rewards, episode_losses).

    train_every: run one gradient step every N environment steps rather
    than every single step -- the same practical throttle the original
    DQN paper (Mnih et al. 2015, section 5) uses ("the agent selects and
    executes actions ... and only performs a learning update every k
    steps"), not an accuracy shortcut."""
    from ..envs.cartpole import STATE_DIM, ACTIONS

    if agent is None:
        agent = DQNAgent(STATE_DIM, len(ACTIONS), state_scale=DEFAULT_STATE_SCALE, seed=seed)

    rewards = []
    losses = []
    global_step = 0
    for ep in range(episodes):
        frac = min(1.0, ep / max(1, epsilon_decay_episodes))
        epsilon = epsilon_start + frac * (epsilon_end - epsilon_start)

        s = env.reset()
        ep_reward = 0.0
        ep_losses = []
        for _ in range(max_steps):
            a = agent.act(s, epsilon)
            ns, r, done, truncated = env.step(a)
            agent.observe(s, a, r, ns, done)
            global_step += 1
            if global_step % train_every == 0:
                loss = agent.learn()
                if loss is not None:
                    ep_losses.append(loss)
            ep_reward += r
            s = ns
            if done or truncated:
                break
        rewards.append(ep_reward)
        losses.append(sum(ep_losses) / len(ep_losses) if ep_losses else None)
        if on_episode:
            on_episode(ep, ep_reward, epsilon)
    return agent, rewards, losses


def evaluate(env, agent, episodes=20, max_steps=500):
    """Greedy (epsilon=0) evaluation, returns list of episode returns."""
    totals = []
    for _ in range(episodes):
        s = env.reset()
        total = 0.0
        for _ in range(max_steps):
            a = agent.act(s, epsilon=0.0)
            s, r, done, truncated = env.step(a)
            total += r
            if done or truncated:
                break
        totals.append(total)
    return totals
