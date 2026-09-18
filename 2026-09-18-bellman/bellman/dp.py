"""Exact dynamic-programming solvers for a deterministic, episodic MDP.

Policy Iteration and Value Iteration both exploit the Bellman equation
directly against the environment's own transition function (no sampling,
no learning rate, no exploration) — they are the ground-truth oracle every
learned (TD) method in td.py is checked against. For an MDP with a proper
optimal policy (one that reaches a terminal state with probability 1, true
for Cliff Walking since a deterministic finite-length path to the goal
always exists), both algorithms are guaranteed to converge to the same
unique optimal value function V*.
"""


def q_values_from_v(env, V, gamma):
    Q = {}
    for s in env.states:
        for a in range(env.n_actions):
            s2, r, done = env.step(s, a)
            v2 = 0.0 if done else V[s2]
            Q[(s, a)] = r + gamma * v2
    return Q


def greedy_policy_from_q(env, Q):
    policy = {}
    for s in env.states:
        policy[s] = max(range(env.n_actions), key=lambda a: Q[(s, a)])
    return policy


def policy_evaluation(env, policy, gamma=1.0, theta=1e-8, max_iterations=5000):
    """Iterative sweeps to a fixed point: V(s) = R(s, pi(s)) + gamma * V(s')."""
    V = {s: 0.0 for s in env.states}
    V[env.goal_state] = 0.0
    for i in range(max_iterations):
        delta = 0.0
        new_V = dict(V)
        for s in env.states:
            a = policy[s]
            s2, r, done = env.step(s, a)
            v2 = 0.0 if done else V[s2]
            new_val = r + gamma * v2
            delta = max(delta, abs(new_val - V[s]))
            new_V[s] = new_val
        V = new_V
        if delta < theta:
            break
    return V


def policy_iteration(env, gamma=1.0, theta=1e-8, max_iterations=1000):
    """Alternate exact policy evaluation and greedy policy improvement
    until the policy stops changing (guaranteed to happen in finitely many
    iterations for a finite MDP)."""
    policy = {s: 0 for s in env.states}
    for iteration in range(max_iterations):
        V = policy_evaluation(env, policy, gamma, theta)
        Q = q_values_from_v(env, V, gamma)
        new_policy = greedy_policy_from_q(env, Q)
        stable = all(new_policy[s] == policy[s] for s in env.states)
        policy = new_policy
        if stable:
            break
    V = policy_evaluation(env, policy, gamma, theta)
    Q = q_values_from_v(env, V, gamma)
    return {
        "V": V,
        "Q": Q,
        "policy": policy,
        "iterations": iteration + 1,
    }


def value_iteration(env, gamma=1.0, theta=1e-8, max_iterations=10000):
    """Directly iterate the Bellman *optimality* backup V(s) <- max_a [...]."""
    V = {s: 0.0 for s in env.states}
    V[env.goal_state] = 0.0
    for iteration in range(max_iterations):
        delta = 0.0
        new_V = dict(V)
        for s in env.states:
            best = None
            for a in range(env.n_actions):
                s2, r, done = env.step(s, a)
                v2 = 0.0 if done else V[s2]
                q = r + gamma * v2
                if best is None or q > best:
                    best = q
            new_V[s] = best
            delta = max(delta, abs(best - V[s]))
        V = new_V
        if delta < theta:
            break
    Q = q_values_from_v(env, V, gamma)
    policy = greedy_policy_from_q(env, Q)
    return {
        "V": V,
        "Q": Q,
        "policy": policy,
        "iterations": iteration + 1,
    }
