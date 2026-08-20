import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bellman.envs.gridworld import GridWorld, make_simple_grid
from bellman.value_iteration import value_iteration


class TestHandSolvableCorridor(unittest.TestCase):
    """A 1x4 corridor: start at column 0, goal at column 3, step_reward=-1,
    goal_reward=0 (the *step that lands on the goal* earns goal_reward,
    not step_reward — see GridWorld.transition). The only sane policy is
    "always go right", and V*(s) is exactly hand-computable:
    V*(3)=0 (absorbing goal), V*(2) = goal_reward + gamma*V*(3) = 0
    (the col2->col3 step *is* the goal-reaching step), V*(1) = step_reward
    + gamma*V*(2), V*(0) = step_reward + gamma*V*(1)."""

    def test_matches_hand_computed_values(self):
        gamma = 0.9
        env = GridWorld(width=4, height=1, start=(0, 0), goal=(0, 3), step_reward=-1.0, goal_reward=0.0)
        V, Q, policy = value_iteration(env, gamma=gamma)

        expected_V3 = 0.0
        expected_V2 = 0.0 + gamma * expected_V3  # goal_reward, not step_reward
        expected_V1 = -1.0 + gamma * expected_V2
        expected_V0 = -1.0 + gamma * expected_V1

        self.assertAlmostEqual(V[env.rc_to_state((0, 3))], expected_V3, places=6)
        self.assertAlmostEqual(V[env.rc_to_state((0, 2))], expected_V2, places=6)
        self.assertAlmostEqual(V[env.rc_to_state((0, 1))], expected_V1, places=6)
        self.assertAlmostEqual(V[env.rc_to_state((0, 0))], expected_V0, places=6)

        # every non-goal cell's optimal action must be "right" (1)
        for c in range(3):
            self.assertEqual(policy[env.rc_to_state((0, c))], 1)


class TestBellmanOptimalityHolds(unittest.TestCase):
    """For every non-terminal state, V*(s) must exactly equal the max
    over actions of the one-step Bellman backup using V* itself — the
    literal defining property of an optimal value function. This is a
    stronger, more general check than comparing to any one hand-solved
    example: it holds for any correctly-converged value function."""

    def test_bellman_equation_satisfied_on_simple_grid(self):
        env = make_simple_grid()
        gamma = 0.95
        V, Q, policy = value_iteration(env, gamma=gamma, theta=1e-12)
        for s in env.all_states():
            if env.is_terminal(s):
                continue
            backups = []
            for a in range(env.n_actions):
                next_s, r, done = env.transition(s, a)
                future = 0.0 if done else V[next_s]
                backups.append(r + gamma * future)
            self.assertAlmostEqual(V[s], max(backups), places=6)

    def test_q_values_consistent_with_v(self):
        env = make_simple_grid()
        gamma = 0.9
        V, Q, policy = value_iteration(env, gamma=gamma)
        for s in env.all_states():
            if env.is_terminal(s):
                continue
            self.assertAlmostEqual(max(Q[s]), V[s], places=8)
            self.assertEqual(policy[s], max(range(env.n_actions), key=lambda a: Q[s][a]))


class TestGoalHasZeroValue(unittest.TestCase):
    def test_goal_value_is_zero(self):
        env = make_simple_grid()
        V, Q, policy = value_iteration(env, gamma=0.9)
        self.assertEqual(V[env.rc_to_state(env.goal_rc)], 0.0)


if __name__ == "__main__":
    unittest.main()
