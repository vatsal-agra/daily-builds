"""Exact dynamic-programming solver for a deterministic tabular MDP.

Used as ground truth: any GridWorld small enough to enumerate exactly can
be solved here to get the *true* optimal value function and Q-function,
which tabular Q-learning/SARSA are then checked against in
tests/test_qlearning.py — a much stronger claim than "reward went up".

Requires the env to expose `all_states()`, `n_actions`, `is_terminal(s)`,
and a pure `transition(state, action) -> (next_state, reward, done)`.
"""

from __future__ import annotations


def value_iteration(env, gamma=0.99, theta=1e-10, max_iter=100_000):
    states = env.all_states()
    V = {s: 0.0 for s in states}

    for _ in range(max_iter):
        delta = 0.0
        for s in states:
            if env.is_terminal(s):
                continue
            best = max(
                _q_backup(env, V, s, a, gamma) for a in range(env.n_actions)
            )
            delta = max(delta, abs(best - V[s]))
            V[s] = best
        if delta < theta:
            break

    Q = {
        s: [_q_backup(env, V, s, a, gamma) for a in range(env.n_actions)]
        for s in states
    }
    policy = {s: max(range(env.n_actions), key=lambda a: Q[s][a]) for s in states}
    return V, Q, policy


def _q_backup(env, V, s, a, gamma):
    next_s, r, done = env.transition(s, a)
    future = 0.0 if done else V.get(next_s, 0.0)
    return r + gamma * future
