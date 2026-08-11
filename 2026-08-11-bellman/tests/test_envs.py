import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.envs import gridworld, cartpole


class TestGridWorldModel(unittest.TestCase):
    def test_registry_builds_all_envs(self):
        for name in gridworld.REGISTRY:
            env = gridworld.make(name)
            self.assertGreater(env.n_states, 0)
            self.assertIsNotNone(env.start_state)

    def test_transition_probabilities_sum_to_one(self):
        for name in gridworld.REGISTRY:
            env = gridworld.make(name)
            for s in range(env.n_states):
                if env.is_wall(s):
                    continue
                for a in env.actions:
                    outcomes = env.transitions(s, a)
                    total = sum(o[0] for o in outcomes)
                    self.assertAlmostEqual(total, 1.0, places=9,
                                            msg=f"{name} s={s} a={a}")

    def test_terminal_states_self_loop_with_zero_reward(self):
        env = gridworld.make("gridworld")
        for s in env.goals | env.holes:
            outcomes = env.transitions(s, gridworld.UP)
            self.assertEqual(len(outcomes), 1)
            prob, ns, r, done = outcomes[0]
            self.assertEqual(ns, s)
            self.assertEqual(r, 0.0)
            self.assertTrue(done)

    def test_walls_are_impassable(self):
        env = gridworld.make("gridworld")
        # cell (0,1) is open; moving DOWN into a wall '#' at (1,1) bumps back
        s = env.state_of(0, 1)
        outcomes = env.transitions(s, gridworld.DOWN)
        self.assertEqual(len(outcomes), 1)
        _, ns, r, done = outcomes[0]
        self.assertEqual(ns, s)  # stayed in place

    def test_reaching_goal_terminates_with_goal_reward(self):
        env = gridworld.make("gridworld")
        # (2,3) is directly above the goal (3,3)
        s = env.state_of(2, 3)
        outcomes = env.transitions(s, gridworld.DOWN)
        self.assertEqual(len(outcomes), 1)
        _, ns, r, done = outcomes[0]
        self.assertEqual(r, env.goal_reward)
        self.assertTrue(done)
        self.assertIn(ns, env.goals)

    def test_cliff_snaps_back_to_start_and_is_not_terminal(self):
        env = gridworld.make("cliffwalking")
        s = env.start_state
        outcomes = env.transitions(s, gridworld.UP)
        _, ns, r, done = outcomes[0]  # UP from start moves onto row 2, safe
        self.assertFalse(done)
        # now step DOWN off the safe row directly onto a cliff cell
        # (row 3, columns 1-4 are 'C'; column 0 is 'S', column 5 is 'G')
        s2 = env.state_of(2, 1)
        outcomes2 = env.transitions(s2, gridworld.DOWN)
        _, ns2, r2, done2 = outcomes2[0]
        self.assertEqual(r2, env.cliff_reward)
        self.assertEqual(ns2, env.start_state)
        self.assertFalse(done2)  # cliff falls don't end the episode

    def test_windy_column_pushes_north(self):
        env = gridworld.make("windygridworld")
        # wind strength is keyed by the column the agent moves *from*
        # (Sutton & Barto's own formulation): standing in a windy column
        # and moving right lands one row higher than the plain move would
        col = 3
        self.assertEqual(env.wind[col], 1)
        r0 = 5
        s = env.state_of(r0, col)
        outcomes = env.transitions(s, gridworld.RIGHT)
        _, ns, reward, done = outcomes[0]
        nr, nc = env.rc(ns)
        self.assertEqual(nc, col + 1)
        self.assertEqual(nr, r0 - 1)  # pushed north by wind strength 1

    def test_frozen_lake_is_stochastic(self):
        env = gridworld.make("frozenlake")
        s = env.start_state
        outcomes = env.transitions(s, gridworld.RIGHT)
        self.assertEqual(len(outcomes), 3)  # intended + 2 perpendicular
        probs = sorted(o[0] for o in outcomes)
        self.assertAlmostEqual(probs[0], env.slip_prob / 2)
        self.assertAlmostEqual(probs[-1], 1 - env.slip_prob)

    def test_reset_and_step_are_consistent_with_the_model(self):
        env = gridworld.make("gridworld")
        s0 = env.reset()
        self.assertEqual(s0, env.start_state)
        ns, r, done, truncated = env.step(gridworld.RIGHT)
        outcomes = env.transitions(s0, gridworld.RIGHT)
        self.assertEqual(ns, outcomes[0][1])
        self.assertEqual(r, outcomes[0][2])


class TestGridWorldInvalidInput(unittest.TestCase):
    def test_empty_grid_raises_a_clean_error(self):
        with self.assertRaises(ValueError):
            gridworld.GridWorld([])

    def test_ragged_grid_raises_a_clean_error(self):
        with self.assertRaises(ValueError):
            gridworld.GridWorld(["...", ".."])


class TestCartPolePhysics(unittest.TestCase):
    def test_reset_gives_small_perturbation_near_origin(self):
        env = cartpole.CartPoleEnv(seed=0)
        s = env.reset()
        self.assertEqual(len(s), 4)
        for v in s:
            self.assertLess(abs(v), 0.06)

    def test_action_must_be_valid(self):
        env = cartpole.CartPoleEnv(seed=0)
        env.reset()
        with self.assertRaises(ValueError):
            env.step(2)

    def test_step_before_reset_raises_a_clean_error(self):
        # regression test: used to crash with a raw, confusing
        # "TypeError: cannot unpack non-iterable NoneType object" instead
        # of a clear error -- GridWorld already guarded this, CartPole
        # didn't, found in adversarial review (REVIEW.md)
        env = cartpole.CartPoleEnv(seed=0)
        with self.assertRaises(RuntimeError):
            env.step(0)

    def test_symmetry_of_the_dynamics(self):
        """Pushing left from a mirrored state should mirror the result of
        pushing right from the original state -- the physics has no
        preferred direction, only the actions do."""
        env_a = cartpole.CartPoleEnv(seed=0)
        env_a.state = (0.0, 0.0, 0.05, 0.0)
        s_a, r_a, done_a, _ = env_a.step(1)  # push right

        env_b = cartpole.CartPoleEnv(seed=0)
        env_b.state = (0.0, 0.0, -0.05, 0.0)
        s_b, r_b, done_b, _ = env_b.step(0)  # push left

        for va, vb in zip(s_a, s_b):
            self.assertAlmostEqual(va, -vb, places=9)

    def test_falls_over_when_unbalanced_and_uncontrolled(self):
        env = cartpole.CartPoleEnv(seed=0)
        env.reset()
        env.state = (0.0, 0.0, 0.15, 0.5)  # already tipping fast
        done = False
        steps = 0
        for _ in range(500):
            s, r, done, truncated = env.step(1)  # push the wrong way on purpose
            steps += 1
            if done:
                break
        self.assertTrue(done)
        self.assertLess(steps, 100)

    def test_heuristic_bang_bang_controller_balances_for_full_horizon(self):
        """A trivial hand-coded controller (push toward the fall
        direction) should balance the pole for the entire episode --
        this is an independent sanity oracle for the physics, not a
        learned result."""
        env = cartpole.CartPoleEnv(max_steps=500, seed=1)
        s = env.reset()
        steps = 0
        done = False
        for _ in range(500):
            _, _, theta, _ = s
            a = 1 if theta > 0 else 0
            s, r, done, truncated = env.step(a)
            steps += 1
            if done or truncated:
                break
        self.assertEqual(steps, 500)
        self.assertFalse(done)  # ran out the clock, didn't fall


if __name__ == "__main__":
    unittest.main()
