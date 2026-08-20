import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bellman.envs.gridworld import GridWorld, make_simple_grid, make_cliff_walking


class TestStateEncoding(unittest.TestCase):
    def test_rc_state_roundtrip(self):
        env = make_simple_grid()
        for r in range(env.height):
            for c in range(env.width):
                s = env.rc_to_state((r, c))
                self.assertEqual(env.state_to_rc(s), (r, c))

    def test_all_states_excludes_walls(self):
        env = make_simple_grid()
        states = env.all_states()
        self.assertEqual(len(states), env.width * env.height - len(env.walls))
        for w in env.walls:
            self.assertNotIn(env.rc_to_state(w), states)


class TestTransitions(unittest.TestCase):
    def setUp(self):
        # 3x3 grid, no walls, goal at (0,2), start at (2,0)
        self.env = GridWorld(width=3, height=3, start=(2, 0), goal=(0, 2))

    def test_move_up_decrements_row(self):
        s0 = self.env.rc_to_state((1, 1))
        s1, r, done = self.env.transition(s0, 0)  # up
        self.assertEqual(self.env.state_to_rc(s1), (0, 1))
        self.assertEqual(r, -1.0)
        self.assertFalse(done)

    def test_move_off_grid_edge_stays_put(self):
        s0 = self.env.rc_to_state((0, 0))
        s1, r, done = self.env.transition(s0, 0)  # up, off the top edge
        self.assertEqual(s1, s0)
        self.assertEqual(r, -1.0)
        self.assertFalse(done)

    def test_move_into_wall_stays_put(self):
        env = GridWorld(width=3, height=3, start=(2, 0), goal=(0, 2), walls={(1, 0)})
        s0 = env.rc_to_state((0, 0))
        s1, r, done = env.transition(s0, 2)  # down, into a wall
        self.assertEqual(s1, s0)

    def test_reaching_goal_terminates_with_goal_reward(self):
        env = GridWorld(width=3, height=3, start=(2, 0), goal=(0, 2), goal_reward=5.0)
        s0 = env.rc_to_state((0, 1))
        s1, r, done = env.transition(s0, 1)  # right, into goal
        self.assertEqual(env.state_to_rc(s1), (0, 2))
        self.assertEqual(r, 5.0)
        self.assertTrue(done)

    def test_goal_is_absorbing(self):
        env = GridWorld(width=3, height=3, start=(2, 0), goal=(0, 2))
        s_goal = env.rc_to_state((0, 2))
        for a in range(4):
            s1, r, done = env.transition(s_goal, a)
            self.assertEqual(s1, s_goal)
            self.assertEqual(r, 0.0)
            self.assertTrue(done)

    def test_is_terminal(self):
        env = self.env
        self.assertTrue(env.is_terminal(env.rc_to_state(env.goal_rc)))
        self.assertFalse(env.is_terminal(env.rc_to_state((1, 1))))


class TestEpisodeAPI(unittest.TestCase):
    def test_reset_returns_start_state(self):
        env = make_simple_grid()
        s = env.reset()
        self.assertEqual(env.state_to_rc(s), env.start_rc)

    def test_step_matches_transition(self):
        env = make_simple_grid()
        s0 = env.reset()
        expected_s1, expected_r, expected_done = env.transition(s0, 1)
        s1, r, done, info = env.step(1)
        self.assertEqual(s1, expected_s1)
        self.assertEqual(r, expected_r)
        # done from step() also ORs in truncation, but on step 1 of a
        # 100-max-steps episode truncation can't have fired yet.
        self.assertEqual(done, expected_done)

    def test_truncates_at_max_steps(self):
        env = GridWorld(width=5, height=5, start=(4, 4), goal=(0, 0), max_steps=3)
        env.reset()
        for i in range(3):
            s, r, done, info = env.step(0)  # walk up forever, never reaching goal
        self.assertTrue(done)
        self.assertTrue(info["truncated"])

    def test_invalid_action_raises(self):
        env = make_simple_grid()
        env.reset()
        with self.assertRaises(ValueError):
            env.step(7)


class TestCliffWalking(unittest.TestCase):
    def test_cliff_transition_returns_to_start_without_terminating(self):
        env = make_cliff_walking()
        # a cell directly above a cliff cell, stepping down into the cliff
        above_cliff = env.rc_to_state((env.height - 2, 5))
        s1, r, done = env.transition(above_cliff, 2)  # down, into the cliff
        self.assertEqual(r, -100.0)
        self.assertFalse(done)
        self.assertEqual(env.state_to_rc(s1), env.start_rc)

    def test_stepping_right_from_start_falls_off_the_cliff(self):
        # by construction the entire bottom row between start and goal is
        # cliff, so the very first "right" move from start is already a
        # cliff step — worth pinning down explicitly since it's easy to
        # get the cliff's column range off by one.
        env = make_cliff_walking()
        env.reset()
        s, r, done, info = env.step(1)  # right
        self.assertEqual(r, -100.0)
        self.assertFalse(done)
        self.assertEqual(env.state_to_rc(s), env.start_rc)

    def test_goal_reachable_and_terminates(self):
        env = make_cliff_walking()
        env.reset()
        # walk straight up, across the top, and back down to the goal
        env.step(0)  # up
        done = False
        for _ in range(env.width - 1):
            _, _, done, _ = env.step(1)  # right
        self.assertFalse(done)  # not yet, still on the top row
        s, r, done, info = env.step(2)  # down, into the goal
        self.assertTrue(done)
        self.assertEqual(env.state_to_rc(s), env.goal_rc)


class TestConstructorValidation(unittest.TestCase):
    def test_start_out_of_bounds_rejected(self):
        with self.assertRaises(ValueError):
            GridWorld(width=3, height=3, start=(5, 5), goal=(0, 0))

    def test_start_on_wall_rejected(self):
        with self.assertRaises(ValueError):
            GridWorld(width=3, height=3, start=(0, 0), goal=(2, 2), walls={(0, 0)})

    def test_start_on_cliff_rejected(self):
        with self.assertRaises(ValueError):
            GridWorld(width=3, height=3, start=(0, 0), goal=(2, 2), cliffs={(0, 0)})


if __name__ == "__main__":
    unittest.main()
