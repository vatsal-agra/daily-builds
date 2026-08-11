"""From-scratch tabular temporal-difference and Monte-Carlo control.

Q-learning is off-policy: it bootstraps from max_a Q(s', a), the value of
the *greedy* action, regardless of what action the behavior policy
actually takes next. SARSA is on-policy: it bootstraps from Q(s', a')
using the action the agent *actually* takes next under its own
(epsilon-greedy) policy. The difference is famously visible on
CliffWalking: Q-learning learns the optimal (risky, cliff-adjacent) path
because it always imagines acting greedily from the next state, while
SARSA learns a safer path because it accounts for its own exploration
noise possibly walking it off the cliff. bellman's test suite reproduces
this divergence explicitly rather than asserting it.
"""
import random


class EpsilonGreedy:
    def __init__(self, epsilon_start=1.0, epsilon_end=0.05, decay_episodes=500):
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.decay_episodes = max(1, decay_episodes)

    def epsilon(self, episode):
        frac = min(1.0, episode / self.decay_episodes)
        return self.epsilon_start + frac * (self.epsilon_end - self.epsilon_start)

    def select(self, q_row, actions, epsilon, rng):
        if rng.random() < epsilon:
            return rng.choice(actions)
        best = max(q_row.values())
        # break ties uniformly at random for a stable, unbiased policy
        candidates = [a for a, v in q_row.items() if v == best]
        return rng.choice(candidates)


class _TabularAgentBase:
    name = "base"

    def __init__(self, env, alpha=0.5, gamma=0.99, schedule=None, seed=0):
        self.env = env
        self.alpha = alpha
        self.gamma = gamma
        self.schedule = schedule or EpsilonGreedy()
        self.rng = random.Random(seed)
        self.Q = {
            s: {a: 0.0 for a in env.actions}
            for s in range(env.n_states)
            if not env.is_wall(s)
        }

    def greedy_policy(self):
        policy = {}
        for s, row in self.Q.items():
            best = max(row.values())
            candidates = [a for a, v in row.items() if v == best]
            policy[s] = sorted(candidates)[0]
        return policy

    def value_function(self):
        return {s: max(row.values()) for s, row in self.Q.items()}

    def train(self, episodes=500, max_steps=None):
        rewards = []
        for ep in range(episodes):
            rewards.append(self._run_episode(ep, max_steps))
        return rewards


class QLearning(_TabularAgentBase):
    """Off-policy TD control: Q(s,a) += alpha*(r + gamma*max_a' Q(s',a') - Q(s,a))."""

    name = "Q-learning"

    def _run_episode(self, ep, max_steps):
        env = self.env
        s = env.reset()
        eps = self.schedule.epsilon(ep)
        total_r = 0.0
        steps = 0
        while True:
            a = self.schedule.select(self.Q[s], env.actions, eps, self.rng)
            ns, r, done, truncated = env.step(a)
            total_r += r
            steps += 1
            target = r if done else r + self.gamma * max(self.Q[ns].values())
            self.Q[s][a] += self.alpha * (target - self.Q[s][a])
            s = ns
            if done or truncated or (max_steps and steps >= max_steps):
                break
        return total_r


class Sarsa(_TabularAgentBase):
    """On-policy TD control: Q(s,a) += alpha*(r + gamma*Q(s',a') - Q(s,a))
    where a' is the action actually chosen next under the current policy."""

    name = "SARSA"

    def _run_episode(self, ep, max_steps):
        env = self.env
        s = env.reset()
        eps = self.schedule.epsilon(ep)
        a = self.schedule.select(self.Q[s], env.actions, eps, self.rng)
        total_r = 0.0
        steps = 0
        while True:
            ns, r, done, truncated = env.step(a)
            total_r += r
            steps += 1
            if done:
                target = r
                na = None
            else:
                na = self.schedule.select(self.Q[ns], env.actions, eps, self.rng)
                target = r + self.gamma * self.Q[ns][na]
            self.Q[s][a] += self.alpha * (target - self.Q[s][a])
            s, a = ns, na
            if done or truncated or (max_steps and steps >= max_steps):
                break
        return total_r


class MonteCarlo(_TabularAgentBase):
    """Every-visit Monte Carlo control: run a full episode with the
    current epsilon-greedy policy, then update every (s,a) pair visited
    toward the *actual observed return* from that point on -- no
    bootstrapping, no bias from an imperfect value estimate, at the cost
    of needing complete episodes and higher variance."""

    name = "Monte Carlo"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._visit_counts = {s: {act: 0 for act in self.env.actions} for s in self.Q}

    def _run_episode(self, ep, max_steps):
        env = self.env
        s = env.reset()
        eps = self.schedule.epsilon(ep)
        trajectory = []
        total_r = 0.0
        steps = 0
        while True:
            a = self.schedule.select(self.Q[s], env.actions, eps, self.rng)
            ns, r, done, truncated = env.step(a)
            trajectory.append((s, a, r))
            total_r += r
            steps += 1
            s = ns
            if done or truncated or (max_steps and steps >= max_steps):
                break

        G = 0.0
        for s, a, r in reversed(trajectory):
            G = r + self.gamma * G
            self._visit_counts[s][a] += 1
            n = self._visit_counts[s][a]
            # incremental sample-mean update: exact average of all
            # observed returns for (s,a), not a fixed learning rate
            self.Q[s][a] += (G - self.Q[s][a]) / n
        return total_r


AGENTS = {"qlearning": QLearning, "sarsa": Sarsa, "montecarlo": MonteCarlo}


def make(name, env, **kw):
    key = name.strip().lower().replace("-", "").replace("_", "")
    if key not in AGENTS:
        raise KeyError(f"unknown tabular agent {name!r}; choices: {sorted(AGENTS)}")
    return AGENTS[key](env, **kw)
