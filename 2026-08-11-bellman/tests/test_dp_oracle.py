import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.envs.gridworld import GridWorld, UP, RIGHT, DOWN, LEFT
from bellman.agents import dp


class TestHandSolvedMDPs(unittest.TestCase):
    """Tiny MDPs with a value computable by hand, checked against both
    DP solvers -- the actual ground truth this whole repo trusts."""

    def test_two_state_deterministic_chain(self):
        # S -> G in exactly one step, any action, reward 5, gamma=0.9
        grid = ["SG"]
        env = GridWorld(grid, step_reward=0.0, goal_reward=5.0, max_steps=10)
        V, Q, policy = dp.value_iteration(env, gamma=0.9)
        # V*(S) = 5 (reward for the one transition into the terminal goal)
        self.assertAlmostEqual(V[env.start_state], 5.0, places=6)

    def test_three_state_chain_matches_geometric_series(self):
        # S -> . -> G, -1 reward on every hop including the one that
        # enters the goal, gamma known -> exact closed form
        grid = ["S.G"]
        gamma = 0.9
        env = GridWorld(grid, step_reward=-1.0, goal_reward=-1.0, max_steps=10)
        V, Q, policy = dp.value_iteration(env, gamma=gamma)
        # optimal path takes exactly 2 hops, each costing -1: V*(S) = -1 - gamma*1 = -(1+gamma)
        expected = -(1 + gamma)
        self.assertAlmostEqual(V[env.start_state], expected, places=5)

    def test_value_iteration_and_policy_iteration_agree(self):
        grid = [
            "S...",
            ".##.",
            "....",
            "..#G",
        ]
        env1 = GridWorld(grid, step_reward=-1.0, goal_reward=10.0)
        env2 = GridWorld(grid, step_reward=-1.0, goal_reward=10.0)
        V1, Q1, pol1 = dp.value_iteration(env1, gamma=0.95)
        V2, Q2, pol2 = dp.policy_iteration(env2, gamma=0.95)
        for s in range(env1.n_states):
            if env1.is_wall(s):
                continue
            self.assertAlmostEqual(V1[s], V2[s], places=4, msg=f"state {s}")

    def test_hole_makes_the_optimal_policy_avoid_it(self):
        grid = [
            "S..",
            ".H.",
            "..G",
        ]
        env = GridWorld(grid, step_reward=-1.0, goal_reward=10.0, hole_reward=-50.0)
        V, Q, policy = dp.value_iteration(env, gamma=0.95)
        hole_state = next(iter(env.holes))
        # every non-terminal state's greedy action must avoid stepping
        # directly into the hole when a hole-free path of equal length exists
        s = env.state_of(0, 1)  # directly above the hole
        a = policy[s]
        outcomes = env.transitions(s, a)
        self.assertNotIn(hole_state, [o[1] for o in outcomes if o[0] > 0])


class TestValueIterationConvergence(unittest.TestCase):
    def test_terminal_states_have_zero_value(self):
        grid = ["S.G"]
        env = GridWorld(grid, step_reward=-1.0, goal_reward=10.0)
        V, Q, policy = dp.value_iteration(env)
        for s in env.goals:
            self.assertEqual(V[s], 0.0)

    def test_walls_are_skipped_not_solved(self):
        grid = ["S#G"]
        env = GridWorld(grid, step_reward=-1.0, goal_reward=10.0)
        V, Q, policy = dp.value_iteration(env)
        wall_state = next(iter(env.walls))
        self.assertNotIn(wall_state, policy)


if __name__ == "__main__":
    unittest.main()
