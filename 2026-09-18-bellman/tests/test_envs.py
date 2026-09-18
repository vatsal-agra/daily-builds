import random
import unittest

from bellman.envs.cartpole import CartPole, THETA_THRESHOLD, X_THRESHOLD
from bellman.envs.cliffwalking import CliffWalking, GOAL, START, to_rc
from bellman.envs.tictactoe import EMPTY_BOARD, apply_move, available_actions, winner


class TestCliffWalkingEnv(unittest.TestCase):
    def test_reset_is_start_state(self):
        env = CliffWalking()
        self.assertEqual(to_rc(env.reset()), START)

    def test_goal_is_terminal(self):
        env = CliffWalking()
        self.assertTrue(env.is_terminal(env.goal_state))
        self.assertEqual(to_rc(env.goal_state), GOAL)

    def test_falling_off_cliff_resets_to_start_with_big_penalty(self):
        env = CliffWalking()
        # from directly above the leftmost cliff cell, step DOWN into it
        from bellman.envs.cliffwalking import DOWN, to_state
        state = to_state(2, 1)
        next_state, reward, done = env.step(state, DOWN)
        self.assertEqual(next_state, env.start_state)
        self.assertEqual(reward, -100.0)
        self.assertFalse(done)

    def test_boundary_actions_do_not_leave_the_grid(self):
        env = CliffWalking()
        from bellman.envs.cliffwalking import LEFT, UP, to_state
        top_left = to_state(0, 0)
        next_state, _, _ = env.step(top_left, UP)
        self.assertEqual(next_state, top_left)
        next_state, _, _ = env.step(top_left, LEFT)
        self.assertEqual(next_state, top_left)


class TestTicTacToeEnv(unittest.TestCase):
    def test_empty_board_has_nine_actions(self):
        self.assertEqual(len(available_actions(EMPTY_BOARD)), 9)

    def test_winner_detects_all_eight_lines(self):
        lines = [
            (0, 1, 2), (3, 4, 5), (6, 7, 8),
            (0, 3, 6), (1, 4, 7), (2, 5, 8),
            (0, 4, 8), (2, 4, 6),
        ]
        for line in lines:
            board = list(" " * 9)
            for i in line:
                board[i] = "X"
            self.assertEqual(winner(tuple(board)), "X")

    def test_no_winner_on_empty_board(self):
        self.assertIsNone(winner(EMPTY_BOARD))


class TestCartPoleEnv(unittest.TestCase):
    def test_reset_state_is_near_zero(self):
        env = CartPole()
        rng = random.Random(0)
        state = env.reset(rng)
        self.assertEqual(len(state), 4)
        for v in state:
            self.assertLess(abs(v), 0.06)

    def test_step_works_without_a_prior_reset(self):
        # step() must be a pure function of (state, action) -- no hidden
        # instance counter that only reset() initializes. A prior version
        # of this environment crashed here with AttributeError.
        env = CartPole(max_steps=200)
        state = (0.0, 0.0, 0.0, 0.0)
        next_state, reward, fell = env.step(state, 1)
        self.assertEqual(len(next_state), 4)
        self.assertEqual(reward, 1.0)
        self.assertFalse(fell)

    def test_episode_runs_up_to_max_steps_under_random_policy(self):
        env = CartPole(max_steps=200)
        rng = random.Random(0)
        state = env.reset(rng)
        steps = 0
        fell = False
        while not fell and steps < 200:
            state, reward, fell = env.step(state, rng.randrange(2))
            self.assertEqual(reward, 1.0)
            steps += 1
        self.assertLessEqual(steps, 200)

    def test_falling_is_reported_immediately(self):
        env = CartPole(max_steps=200)
        # start tipped hard over the failure threshold already
        state = (0.0, 0.0, THETA_THRESHOLD + 0.5, 0.0)
        state, reward, fell = env.step(state, 1)
        self.assertTrue(fell)

    def test_normalize_keeps_values_bounded(self):
        env = CartPole()
        norm = env.normalize((X_THRESHOLD, 2.0, THETA_THRESHOLD, 3.0))
        for v in norm:
            self.assertLessEqual(abs(v), 1.0001)


if __name__ == "__main__":
    unittest.main()
