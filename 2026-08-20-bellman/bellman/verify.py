"""Shared verification helpers used by both train.py (to print/save
verification results after a real training run) and the test suite (to
assert on them directly) — one implementation, not two copies that could
quietly drift apart.
"""

from __future__ import annotations

from .value_iteration import value_iteration


def rollout_discounted_return(env, policy, gamma, max_steps=200):
    """Rolls out a purely greedy policy from the env's start state and
    returns the realized discounted return. Since GridWorld transitions
    are deterministic, this is exactly comparable to value iteration's
    V* at the start state."""
    s = env.reset()
    total, discount, steps = 0.0, 1.0, 0
    while steps < max_steps:
        s, r, done, info = env.step(policy[s])
        total += discount * r
        discount *= gamma
        steps += 1
        if done:
            break
    return total


def verify_against_value_iteration(env, agent, gamma):
    """Returns a dict describing how well agent.Q/greedy_policy() matches
    an exact value-iteration solve of env. `optimal_rollout` is the
    strong, tie-robust claim: does executing the learned greedy policy
    from the start state realize the true optimal discounted return."""
    V, Q, opt_policy = value_iteration(env, gamma=gamma)
    learned_policy = agent.greedy_policy()
    states = env.all_states()
    action_matches = sum(1 for s in states if learned_policy[s] == opt_policy[s])
    value_close = sum(1 for s in states if abs(agent.Q[s][learned_policy[s]] - V[s]) < 0.5)

    start_state = env.rc_to_state(env.start_rc)
    optimal_return = V[start_state]
    achieved_return = rollout_discounted_return(env, learned_policy, gamma, env.max_steps)

    return {
        "optimal_rollout": abs(achieved_return - optimal_return) < 1e-6,
        "achieved_return": achieved_return,
        "optimal_return": optimal_return,
        "action_matches": action_matches,
        "value_close": value_close,
        "total_states": len(states),
    }


def greedy_path(env, policy, max_steps=200):
    """Rolls out a purely greedy policy from the start, returning the
    list of (row, col) cells visited — used for the cliff-walking
    divergence check and the HTML report's path replay."""
    state = env.reset()
    path = [env.state_to_rc(state)]
    for _ in range(max_steps):
        action = policy[state]
        state, reward, done, info = env.step(action)
        path.append(env.state_to_rc(state))
        if done:
            break
    return path


def cliff_edge_fraction(env, path):
    """Fraction of a cliff-walking path's interior cells (excluding
    start/goal, which must touch the edge row to enter/exit it) that lie
    in the row directly above the cliff. The risky optimal path walks the
    entire edge row (~1.0); a safer path only brushes it in passing."""
    edge_row = env.height - 2
    interior = path[1:-1] or path
    return sum(1 for r, c in interior if r == edge_row) / len(interior)
