"""Small shared helpers used by viz_export.py and the test suite."""


def rollout_policy(env, policy, max_steps=200):
    """Simulate a deterministic greedy policy from the start state. Returns
    (states_visited, total_reward, reached_goal). Capped at max_steps so a
    policy that never reaches the goal (e.g. a badly-undertrained one)
    can't hang the caller -- reached_goal=False signals that case rather
    than pretending the truncated return is the policy's true value."""
    s = env.reset()
    states = [s]
    total_reward = 0.0
    for _ in range(max_steps):
        a = policy[s]
        s2, r, done = env.step(s, a)
        total_reward += r
        states.append(s2)
        s = s2
        if done:
            return states, total_reward, True
    return states, total_reward, False
