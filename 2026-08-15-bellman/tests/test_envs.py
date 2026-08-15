import math
import unittest

from bellman.envs import GridWorldEnv, CartPoleEnv, BlackjackEnv


class TestGridWorldEnv(unittest.TestCase):
    def test_deterministic_step_matches_intended_action(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        s = env.reset()
        self.assertEqual(env.decode(s), (3, 0))
        ns, r, done, _ = env.step(0)  # up
        self.assertEqual(env.decode(ns), (2, 0))
        self.assertEqual(r, -1.0)
        self.assertFalse(done)

    def test_cliff_sends_back_to_start_with_penalty(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        env.reset()
        ns, r, done, _ = env.step(1)  # right, into the cliff cell (3,1)
        self.assertEqual(env.decode(ns), (3, 0))
        self.assertEqual(r, -100.0)
        self.assertFalse(done)

    def test_goal_terminates_with_no_penalty_beyond_step_cost(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        env.state = env.encode(3, 10)  # one cell left of goal
        ns, r, done, _ = env.step(1)  # right, into goal
        self.assertEqual(env.decode(ns), (3, 11))
        self.assertTrue(done)

    def test_transition_model_probabilities_sum_to_one(self):
        for slip in (0.0, 0.1, 0.3):
            env = GridWorldEnv(rows=4, cols=12, slip_prob=slip)
            for s in env.states:
                if env.is_terminal(s):
                    continue
                for a in env.actions:
                    total = sum(p for p, _, _, _ in env.transition_model(s, a))
                    self.assertAlmostEqual(total, 1.0, places=9,
                                            msg=f"state={s} action={a} slip={slip}")

    def test_walls_clamp_rather_than_wrap(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        env.state = env.encode(0, 0)
        ns, r, done, _ = env.step(0)  # up, already at top row
        self.assertEqual(env.decode(ns), (0, 0))

    def test_slippery_transition_has_multiple_outcomes(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.3)
        outcomes = env.transition_model(env.encode(1, 5), 0)  # interior state, up
        self.assertGreater(len(outcomes), 1)

    def test_render_ascii_shapes(self):
        env = GridWorldEnv(rows=4, cols=12)
        text = env.render_ascii()
        lines = text.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(len(lines[0].split()), 12)

    def test_rejects_degenerate_dimensions(self):
        # Regression test: rows=1 puts the cliff on the *only* row (no row
        # above to detour through), making the goal provably unreachable --
        # value_iteration used to just fail to converge with a confusing
        # error instead of the constructor rejecting the input outright.
        with self.assertRaises(ValueError):
            GridWorldEnv(rows=1, cols=12)
        with self.assertRaises(ValueError):
            GridWorldEnv(rows=4, cols=1)

    def test_rejects_invalid_slip_probability(self):
        with self.assertRaises(ValueError):
            GridWorldEnv(slip_prob=1.5)
        with self.assertRaises(ValueError):
            GridWorldEnv(slip_prob=-0.1)


class TestCartPoleEnv(unittest.TestCase):
    def test_reset_gives_small_random_state(self):
        env = CartPoleEnv(seed=0)
        s = env.reset()
        self.assertEqual(len(s), 4)
        for v in s:
            self.assertLessEqual(abs(v), 0.05)

    def test_upright_at_rest_stays_near_upright_one_step(self):
        env = CartPoleEnv(seed=0)
        env.state = (0.0, 0.0, 0.0, 0.0)
        env.steps = 0
        ns, r, done, _ = env.step(1)
        self.assertFalse(done)
        self.assertEqual(r, 1.0)
        # after one 0.02s step from dead-still upright, displacement should be tiny
        self.assertLess(abs(ns[2]), 0.01)

    def test_falls_over_and_terminates_eventually(self):
        env = CartPoleEnv(max_steps=500, seed=0)
        env.state = (0.0, 0.0, 0.25, 0.0)  # start already past the 12-degree limit
        env.steps = 0
        _, _, done, _ = env.step(1)
        self.assertTrue(done)

    def test_episode_terminates_by_max_steps_if_never_falls(self):
        env = CartPoleEnv(max_steps=5, seed=0)
        env.state = (0.0, 0.0, 0.0, 0.0)
        env.steps = 0
        done = False
        n = 0
        # alternate actions to keep the pole roughly balanced for a few steps
        while not done and n < 10:
            _, _, done, _ = env.step(n % 2)
            n += 1
        self.assertTrue(done)
        self.assertLessEqual(n, 5)

    def test_left_and_right_forces_are_mirror_symmetric(self):
        env_l = CartPoleEnv(seed=0)
        env_r = CartPoleEnv(seed=0)
        env_l.state = env_r.state = (0.0, 0.0, 0.0, 0.0)
        env_l.steps = env_r.steps = 0
        sl, _, _, _ = env_l.step(0)
        sr, _, _, _ = env_r.step(1)
        for a, b in zip(sl, sr):
            self.assertAlmostEqual(a, -b, places=9)


class TestBlackjackEnv(unittest.TestCase):
    def test_sum_hand_usable_ace(self):
        total, usable = BlackjackEnv._sum_hand([1, 9])
        self.assertEqual((total, usable), (20, True))

    def test_sum_hand_ace_downgrades_when_busting(self):
        total, usable = BlackjackEnv._sum_hand([1, 9, 5])
        self.assertEqual((total, usable), (15, False))

    def test_hit_past_21_busts(self):
        env = BlackjackEnv(seed=0)
        env.player = [10, 9]
        env.dealer = [5, 5]
        env.done = False
        env.player.append(10)  # force a bust-inducing next draw manually via step's own draw instead:
        env.player = [10, 9]   # reset back; step() will draw its own card
        # Run many seeds until we observe a bust, to prove the mechanism (not luck-dependent assertion).
        busted = False
        for seed in range(200):
            e = BlackjackEnv(seed=seed)
            e.player = [10, 9]
            e.dealer = [5, 5]
            e.done = False
            _, r, done, _ = e.step(1)
            if done and r == -1.0:
                busted = True
                break
        self.assertTrue(busted)

    def test_reset_to_reconstructs_exact_state(self):
        env = BlackjackEnv(seed=0)
        for total in range(12, 22):
            for ace in (False, True):
                obs = env.reset_to(total, 7, ace)
                self.assertEqual(obs, (total, 7, ace))

    def test_resolve_natural_push_on_dealer_natural(self):
        env = BlackjackEnv(seed=0)
        env.player = [1, 10]
        env.dealer = [1, 10]
        result = env.resolve_natural()
        self.assertIsNotNone(result)
        _, reward, done, _ = result
        self.assertEqual(reward, 0.0)
        self.assertTrue(done)

    def test_resolve_natural_win_otherwise(self):
        env = BlackjackEnv(seed=0)
        env.player = [1, 10]
        env.dealer = [9, 8]
        _, reward, done, _ = env.resolve_natural()
        self.assertEqual(reward, 1.0)
        self.assertTrue(done)

    def test_step_after_done_raises_instead_of_silently_continuing(self):
        env = BlackjackEnv(seed=0)
        env.player = [10, 9]
        env.dealer = [9, 8]
        env.step(0)  # stick -> resolves, done=True
        self.assertTrue(env.done)
        with self.assertRaises(RuntimeError):
            env.step(1)

    def test_reset_to_rejects_out_of_range_inputs(self):
        env = BlackjackEnv(seed=0)
        with self.assertRaises(ValueError):
            env.reset_to(11, 5, False)  # below the graded 12..21 range
        with self.assertRaises(ValueError):
            env.reset_to(15, 11, False)  # invalid dealer up-card

    def test_dealer_plays_fixed_policy_hits_below_17(self):
        env = BlackjackEnv(seed=1)
        env.player = [10, 8]  # 18, will stick immediately
        env.dealer = [2, 4]   # 6, must hit
        _, _, done, _ = env.step(0)
        self.assertTrue(done)
        total, _ = BlackjackEnv._sum_hand(env.dealer)
        self.assertTrue(total >= 17 or total > 21)


if __name__ == "__main__":
    unittest.main()
