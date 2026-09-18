"""Tabular temporal-difference control: SARSA (on-policy) and Q-learning
(off-policy), both epsilon-greedy over a learned action-value table Q.

Neither algorithm is ever told the environment's transition or reward
function directly (unlike dp.py) — they only see the (state, reward,
next_state, done) tuples env.step() hands back, one at a time, and update
Q incrementally from that experience alone. The one-step Bellman target is
where the two diverge:

  SARSA:      target = r + gamma * Q[s', a']       (a' is the action the
                                                      behavior policy will
                                                      actually take next —
                                                      "on-policy")
  Q-learning: target = r + gamma * max_a' Q[s', a']  (the best action
                                                      available, whether or
                                                      not epsilon-greedy
                                                      would pick it —
                                                      "off-policy")

On Cliff Walking this produces the famous Sutton & Barto Figure 6.13
split: Q-learning's greedy policy hugs the cliff edge (the true shortest
path); SARSA's greedy policy detours along the safe top row, because its
on-policy target accounts for the real chance that the exploring
epsilon-greedy behavior policy steps off the edge near the cliff.
"""
import random


def epsilon_greedy_action(Q, state, n_actions, epsilon, rng):
    if rng.random() < epsilon:
        return rng.randrange(n_actions)
    qs = [Q[(state, a)] for a in range(n_actions)]
    best_q = max(qs)
    best_actions = [a for a, q in enumerate(qs) if q == best_q]
    return rng.choice(best_actions)


def greedy_policy(env, Q):
    return {
        s: max(range(env.n_actions), key=lambda a: Q[(s, a)])
        for s in env.states
    }


def _init_q(env):
    return {(s, a): 0.0 for s in env.states for a in range(env.n_actions)}


def sarsa(env, episodes=500, alpha=0.5, gamma=1.0, epsilon=0.1, seed=0,
          max_steps_per_episode=2000):
    rng = random.Random(seed)
    Q = _init_q(env)
    episode_returns = []
    for _ in range(episodes):
        s = env.reset()
        a = epsilon_greedy_action(Q, s, env.n_actions, epsilon, rng)
        total_reward = 0.0
        for _ in range(max_steps_per_episode):
            s2, r, done = env.step(s, a)
            total_reward += r
            if done:
                Q[(s, a)] += alpha * (r - Q[(s, a)])
                break
            a2 = epsilon_greedy_action(Q, s2, env.n_actions, epsilon, rng)
            target = r + gamma * Q[(s2, a2)]
            Q[(s, a)] += alpha * (target - Q[(s, a)])
            s, a = s2, a2
        episode_returns.append(total_reward)
    return {"Q": Q, "policy": greedy_policy(env, Q), "returns": episode_returns}


def q_learning(env, episodes=500, alpha=0.5, gamma=1.0, epsilon=0.1, seed=0,
               max_steps_per_episode=2000):
    rng = random.Random(seed)
    Q = _init_q(env)
    episode_returns = []
    for _ in range(episodes):
        s = env.reset()
        total_reward = 0.0
        for _ in range(max_steps_per_episode):
            a = epsilon_greedy_action(Q, s, env.n_actions, epsilon, rng)
            s2, r, done = env.step(s, a)
            total_reward += r
            if done:
                Q[(s, a)] += alpha * (r - Q[(s, a)])
                break
            best_next = max(Q[(s2, a2)] for a2 in range(env.n_actions))
            target = r + gamma * best_next
            Q[(s, a)] += alpha * (target - Q[(s, a)])
            s = s2
        episode_returns.append(total_reward)
    return {"Q": Q, "policy": greedy_policy(env, Q), "returns": episode_returns}


def sarsa_lambda(env, episodes=500, alpha=0.1, gamma=1.0, epsilon=0.1,
                  lam=0.9, seed=0, max_steps_per_episode=2000):
    """Backward-view SARSA(lambda) with *replacing* eligibility traces.
    A stretch extension over one-step SARSA: every state-action pair
    visited this episode gets a share of credit for the eventual TD error,
    decayed by (gamma * lambda) per step since it was last visited, so
    reward information propagates back over many states in a single
    episode instead of one state per step.

    Traces are reset to 1.0 on each (re)visit rather than accumulated
    (E += 1.0). Cliff Walking is loopy under early, mostly-random
    exploration -- falling off the cliff sends the agent straight back to
    the start, so the (start, action) pair the agent keeps re-entering
    from can be visited dozens of times in one long early episode.
    Accumulating traces let E for that pair grow unboundedly across those
    revisits, and the next TD error gets multiplied by that inflated trace
    for every state still in it -- in practice this diverges (Q values in
    the thousands, no stable policy) rather than converging faster than
    1-step SARSA. Replacing traces cap each pair's credit at 1.0 no matter
    how many times it's revisited before the backup, which keeps the
    updates on the same scale as 1-step SARSA and actually converges.
    """
    rng = random.Random(seed)
    Q = _init_q(env)
    episode_returns = []
    for _ in range(episodes):
        E = {k: 0.0 for k in Q}
        s = env.reset()
        a = epsilon_greedy_action(Q, s, env.n_actions, epsilon, rng)
        total_reward = 0.0
        for _ in range(max_steps_per_episode):
            s2, r, done = env.step(s, a)
            total_reward += r
            if done:
                delta = r - Q[(s, a)]
                a2 = None
            else:
                a2 = epsilon_greedy_action(Q, s2, env.n_actions, epsilon, rng)
                delta = r + gamma * Q[(s2, a2)] - Q[(s, a)]
            E[(s, a)] = 1.0
            for key in Q:
                if E[key] != 0.0:
                    Q[key] += alpha * delta * E[key]
                    E[key] *= gamma * lam
            if done:
                break
            s, a = s2, a2
        episode_returns.append(total_reward)
    return {"Q": Q, "policy": greedy_policy(env, Q), "returns": episode_returns}
