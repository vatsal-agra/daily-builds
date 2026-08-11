"""Exact dynamic-programming solvers for the gridworld MDPs.

Value iteration solves the Bellman optimality equation

    V*(s) = max_a sum_{s'} P(s'|s,a) [ R(s,a,s') + gamma * V*(s') ]

to a fixed point by repeated application as a contraction mapping (gamma <
1 guarantees convergence). This is the ground truth every tabular agent
in bellman.agents.tabular is checked against -- it doesn't sample, it
reads the environment's exact transition model.
"""


def value_iteration(env, gamma=0.99, theta=1e-8, max_iters=100_000):
    """Returns (V, Q, policy): optimal state values, action values, and a
    greedy deterministic policy (dict state -> action)."""
    V = [0.0 for _ in range(env.n_states)]
    for it in range(max_iters):
        delta = 0.0
        new_V = V[:]
        for s in range(env.n_states):
            if env.is_wall(s):
                continue
            if env.is_terminal(s):
                new_V[s] = 0.0
                continue
            best = float("-inf")
            for a in env.actions:
                q = _action_value(env, V, s, a, gamma)
                if q > best:
                    best = q
            new_V[s] = best
            delta = max(delta, abs(new_V[s] - V[s]))
        V = new_V
        if delta < theta:
            break
    else:
        raise RuntimeError("value iteration did not converge")

    Q = {}
    policy = {}
    for s in range(env.n_states):
        if env.is_wall(s):
            continue
        qvals = {a: _action_value(env, V, s, a, gamma) for a in env.actions}
        Q[s] = qvals
        if env.is_terminal(s):
            policy[s] = env.actions[0]
        else:
            policy[s] = max(qvals, key=qvals.get)
    return V, Q, policy


def _action_value(env, V, s, a, gamma):
    total = 0.0
    for prob, ns, r, done in env.transitions(s, a):
        future = 0.0 if done else V[ns]
        total += prob * (r + gamma * future)
    return total


def policy_iteration(env, gamma=0.99, theta=1e-8, max_iters=10_000):
    """Alternative exact solver: alternates full policy evaluation with
    greedy policy improvement until the policy stops changing. Used in
    tests as an independent cross-check against value_iteration."""
    policy = {s: env.actions[0] for s in range(env.n_states) if not env.is_wall(s)}
    V = [0.0 for _ in range(env.n_states)]

    for _ in range(max_iters):
        # policy evaluation to convergence
        for _ in range(max_iters):
            delta = 0.0
            for s in policy:
                if env.is_terminal(s):
                    continue
                v = _action_value(env, V, s, policy[s], gamma)
                delta = max(delta, abs(v - V[s]))
                V[s] = v
            if delta < theta:
                break
        # policy improvement
        stable = True
        for s in policy:
            if env.is_terminal(s):
                continue
            old = policy[s]
            qvals = {a: _action_value(env, V, s, a, gamma) for a in env.actions}
            best = max(qvals, key=qvals.get)
            policy[s] = best
            if best != old:
                stable = False
        if stable:
            break
    Q = {s: {a: _action_value(env, V, s, a, gamma) for a in env.actions} for s in policy}
    return V, Q, policy
