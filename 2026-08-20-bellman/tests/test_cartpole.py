import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bellman.envs.cartpole import CartPole


class TestCartPoleBasics(unittest.TestCase):
    def test_reset_state_is_small_and_bounded(self):
        env = CartPole(seed=0)
        s = env.reset()
        self.assertEqual(len(s), 4)
        for v in s:
            self.assertLessEqual(abs(v), 0.05)

    def test_reward_always_one_while_alive(self):
        env = CartPole(seed=0)
        env.reset()
        for _ in range(20):
            s, r, done, info = env.step(1)
            self.assertEqual(r, 1.0)
            if done:
                break

    def test_invalid_action_raises(self):
        env = CartPole(seed=0)
        env.reset()
        with self.assertRaises(ValueError):
            env.step(2)

    def test_seeded_resets_are_reproducible(self):
        env1 = CartPole(seed=42)
        env2 = CartPole(seed=42)
        s1 = env1.reset()
        s2 = env2.reset()
        self.assertEqual(s1, s2)

    def test_seed_changes_reset_state(self):
        env = CartPole(seed=1)
        env.seed(1)
        s1 = env.reset()
        env.seed(2)
        s2 = env.reset()
        self.assertNotEqual(s1, s2)

    def test_same_action_sequence_from_same_seed_is_deterministic(self):
        def run(seed):
            env = CartPole(seed=seed)
            env.reset()
            trace = []
            for i in range(30):
                a = i % 2
                s, r, done, info = env.step(a)
                trace.append(s)
                if done:
                    break
            return trace

        self.assertEqual(run(7), run(7))


class TestCartPolePhysics(unittest.TestCase):
    def test_cart_accelerates_in_the_pushed_direction_from_upright_rest(self):
        """Basic Newtonian sanity, independent of the pole coupling
        details: starting perfectly upright and at rest, pushing the cart
        right must make it move right, and pushing left must make it
        move left (F=ma, not decoupled from the pole but not reversed by
        it either for a light pole starting upright)."""
        env_r = CartPole(max_steps=5)
        env_r._state = (0.0, 0.0, 0.0, 0.0)
        env_r._t = 0
        s_r, _, _, _ = env_r.step(1)  # push right
        self.assertGreater(s_r[1], 0.0)  # x_dot > 0
        self.assertGreater(s_r[0], 0.0)  # x > 0

        env_l = CartPole(max_steps=5)
        env_l._state = (0.0, 0.0, 0.0, 0.0)
        env_l._t = 0
        s_l, _, _, _ = env_l.step(0)  # push left
        self.assertLess(s_l[1], 0.0)
        self.assertLess(s_l[0], 0.0)

    def test_falling_pole_accelerates_away_from_upright_without_intervention(self):
        """A pole already past the point of no return (large tilt, already
        rotating further that way) must keep rotating further that way —
        alternately pushing left/right (a "do nothing useful" policy)
        can't out-fight gravity once the pole is well past vertical."""
        env = CartPole(max_steps=500)
        env._state = (0.0, 0.0, 0.15, 0.5)  # tilted and already falling that way
        env._t = 0
        thetas = [0.15]
        for i in range(10):
            s, r, done, info = env.step(i % 2)  # alternate push direction
            thetas.append(s[2])
            if done:
                break
        self.assertGreater(thetas[-1], thetas[0])

    def test_matches_hand_derived_reference_equations(self):
        """A one-step differential check against the textbook
        Barto/Sutton/Anderson equations of motion, written independently
        (not by calling into cartpole.py), from an arbitrary non-trivial
        state — catches transcription bugs (swapped terms, wrong sign,
        updating position before velocity) in the real implementation."""
        x, x_dot, theta, theta_dot = 0.3, -0.4, 0.12, -0.25
        env = CartPole()
        env._state = (x, x_dot, theta, theta_dot)
        env._t = 0
        action = 1
        s, r, done, info = env.step(action)

        force = env.FORCE_MAG if action == 1 else -env.FORCE_MAG
        costheta, sintheta = math.cos(theta), math.sin(theta)
        temp = (force + env.POLE_MASS_LENGTH * theta_dot * theta_dot * sintheta) / env.TOTAL_MASS
        theta_acc = (env.GRAVITY * sintheta - costheta * temp) / (
            env.HALF_LENGTH * (4.0 / 3.0 - env.MASS_POLE * costheta * costheta / env.TOTAL_MASS)
        )
        x_acc = temp - env.POLE_MASS_LENGTH * theta_acc * costheta / env.TOTAL_MASS
        exp_x_dot = x_dot + env.TAU * x_acc
        exp_x = x + env.TAU * exp_x_dot
        exp_theta_dot = theta_dot + env.TAU * theta_acc
        exp_theta = theta + env.TAU * exp_theta_dot

        self.assertAlmostEqual(s[0], exp_x, places=12)
        self.assertAlmostEqual(s[1], exp_x_dot, places=12)
        self.assertAlmostEqual(s[2], exp_theta, places=12)
        self.assertAlmostEqual(s[3], exp_theta_dot, places=12)

    def test_terminates_when_angle_exceeds_threshold(self):
        env = CartPole(max_steps=1000)
        env._state = (0.0, 0.0, env.THETA_THRESHOLD - 0.001, 5.0)  # falling fast
        env._t = 0
        done = False
        for _ in range(50):
            s, r, done, info = env.step(1)
            if done:
                break
        self.assertTrue(done)
        self.assertTrue(info["fell"])
        self.assertGreater(abs(s[2]), env.THETA_THRESHOLD)

    def test_terminates_when_cart_leaves_track(self):
        env = CartPole(max_steps=1000)
        env._state = (env.X_THRESHOLD - 0.001, 5.0, 0.0, 0.0)  # cart flying off the edge
        env._t = 0
        done = False
        for _ in range(50):
            s, r, done, info = env.step(1)
            if done:
                break
        self.assertTrue(done)
        self.assertTrue(info["fell"])
        self.assertGreater(abs(s[0]), env.X_THRESHOLD)

    def test_truncates_at_max_steps_without_falling(self):
        env = CartPole(max_steps=5)
        env.reset()
        done = False
        steps = 0
        for _ in range(10):
            s, r, done, info = env.step(0)
            steps += 1
            if done:
                break
        self.assertEqual(steps, 5)
        self.assertTrue(info["truncated"])
        self.assertFalse(info["fell"])

    def test_symmetry_left_vs_right_push(self):
        """Pushing left from a mirrored initial state should produce a
        mirrored trajectory of an otherwise-identical right push — the
        physics has no built-in left/right bias."""
        env_r = CartPole(max_steps=10)
        env_r._state = (0.0, 0.0, 0.02, 0.0)
        env_r._t = 0
        s_r, _, _, _ = env_r.step(1)

        env_l = CartPole(max_steps=10)
        env_l._state = (0.0, 0.0, -0.02, 0.0)
        env_l._t = 0
        s_l, _, _, _ = env_l.step(0)

        for a, b in zip(s_r, s_l):
            self.assertAlmostEqual(a, -b, places=10)


if __name__ == "__main__":
    unittest.main()
