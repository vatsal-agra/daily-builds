"""Tabular temporal-difference control: Q-Learning (off-policy) and SARSA
(on-policy). Both learn purely from `env.step()` samples -- neither is ever
given `env.transition_model()`; that's what makes `dp.py`'s Value Iteration
a fair oracle to grade them against.
"""
import random


def epsilon_greedy(Q, state, actions, epsilon, rng):
    if rng.random() < epsilon:
        return rng.choice(actions)
    return max(actions, key=lambda a: Q[state][a])


def _linear_decay(start, end, t, total):
    if total <= 1:
        return end
    frac = min(t / (total - 1), 1.0)
    return start + frac * (end - start)


def q_learning(env, episodes=500, alpha=0.5, gamma=1.0,
               epsilon_start=1.0, epsilon_end=0.01, max_steps=10_000, seed=0,
               on_episode_end=None):
    """Off-policy TD control (Watkins 1989):
        Q(s,a) <- Q(s,a) + alpha * [ r + gamma * max_a' Q(s',a') - Q(s,a) ]
    Learns the value of the *greedy* policy regardless of how it explores.

    `on_episode_end(episode, Q)`, if given, is called after every episode --
    e.g. `train.py`'s viz snapshotting hooks in here instead of maintaining a
    second, separately-drifting copy of this training loop.
    """
    rng = random.Random(seed)
    Q = {s: {a: 0.0 for a in env.actions} for s in env.states}
    episode_returns = []

    for ep in range(episodes):
        epsilon = _linear_decay(epsilon_start, epsilon_end, ep, episodes)
        s = env.reset()
        total_reward = 0.0
        for _ in range(max_steps):
            a = epsilon_greedy(Q, s, env.actions, epsilon, rng)
            ns, r, done, _ = env.step(a)
            total_reward += r
            best_next = 0.0 if done else max(Q[ns].values())
            Q[s][a] += alpha * (r + gamma * best_next - Q[s][a])
            s = ns
            if done:
                break
        episode_returns.append(total_reward)
        if on_episode_end is not None:
            on_episode_end(ep, Q)

    policy = {s: max(env.actions, key=lambda a: Q[s][a]) for s in env.states}
    return Q, policy, episode_returns


def sarsa(env, episodes=500, alpha=0.5, gamma=1.0,
          epsilon_start=1.0, epsilon_end=0.01, max_steps=10_000, seed=0):
    """On-policy TD control (Rummery & Niranjan 1994):
        Q(s,a) <- Q(s,a) + alpha * [ r + gamma * Q(s',a') - Q(s,a) ]
    where a' is the action the *behavior* policy actually takes next --
    SARSA learns the value of the policy it is following, exploration and
    all, which is why it prefers the safer path near a cliff while epsilon
    is still non-trivial.
    """
    rng = random.Random(seed)
    Q = {s: {a: 0.0 for a in env.actions} for s in env.states}
    episode_returns = []

    for ep in range(episodes):
        epsilon = _linear_decay(epsilon_start, epsilon_end, ep, episodes)
        s = env.reset()
        a = epsilon_greedy(Q, s, env.actions, epsilon, rng)
        total_reward = 0.0
        for _ in range(max_steps):
            ns, r, done, _ = env.step(a)
            total_reward += r
            if done:
                Q[s][a] += alpha * (r - Q[s][a])
                break
            na = epsilon_greedy(Q, ns, env.actions, epsilon, rng)
            Q[s][a] += alpha * (r + gamma * Q[ns][na] - Q[s][a])
            s, a = ns, na
        episode_returns.append(total_reward)

    policy = {s: max(env.actions, key=lambda a: Q[s][a]) for s in env.states}
    return Q, policy, episode_returns


def sarsa_lambda(env, episodes=500, alpha=0.5, gamma=1.0, lam=0.9,
                  epsilon_start=1.0, epsilon_end=0.01, max_steps=10_000, seed=0):
    """SARSA(lambda) with accumulating eligibility traces (stretch feature).

    Every state-action pair's eligibility decays by gamma*lambda each step
    but spikes back to 1 on visit, so a single TD error propagates credit
    back through the *whole* recently-visited trajectory in one update
    instead of one step at a time -- converges in fewer episodes than plain
    SARSA on the same task.
    """
    rng = random.Random(seed)
    Q = {s: {a: 0.0 for a in env.actions} for s in env.states}
    episode_returns = []

    for ep in range(episodes):
        epsilon = _linear_decay(epsilon_start, epsilon_end, ep, episodes)
        E = {s: {a: 0.0 for a in env.actions} for s in env.states}
        s = env.reset()
        a = epsilon_greedy(Q, s, env.actions, epsilon, rng)
        total_reward = 0.0
        for _ in range(max_steps):
            ns, r, done, _ = env.step(a)
            total_reward += r
            na = None if done else epsilon_greedy(Q, ns, env.actions, epsilon, rng)
            target = r if done else r + gamma * Q[ns][na]
            delta = target - Q[s][a]
            E[s][a] += 1.0
            for st in E:
                for act in E[st]:
                    if E[st][act] == 0.0:
                        continue
                    Q[st][act] += alpha * delta * E[st][act]
                    E[st][act] *= gamma * lam
            if done:
                break
            s, a = ns, na
        episode_returns.append(total_reward)

    policy = {s: max(env.actions, key=lambda a: Q[s][a]) for s in env.states}
    return Q, policy, episode_returns
