import unittest

from bellman.envs import GridWorldEnv, CartPoleEnv, BlackjackEnv
from bellman.td import q_learning, sarsa, sarsa_lambda
from bellman.mc import mc_control, mc_es_control
from bellman.pg import train_reinforce
from bellman.validation import require_positive_episodes


class TestValidation(unittest.TestCase):
    def test_require_positive_episodes_rejects_bad_input(self):
        for bad in (0, -1, -100, 1.5, "500", None):
            with self.assertRaises(ValueError, msg=f"should reject {bad!r}"):
                require_positive_episodes(bad)

    def test_require_positive_episodes_accepts_good_input(self):
        for good in (1, 2, 500, 1_000_000):
            require_positive_episodes(good)  # must not raise

    def test_every_training_entry_point_rejects_zero_episodes(self):
        # Polish pass (Phase 4): episodes=0 used to silently "succeed" with
        # an empty reward history and an untrained policy that looked like a
        # real (if bad) result -- now it's a clear, immediate ValueError.
        cases = [
            (q_learning, (GridWorldEnv(),)),
            (sarsa, (GridWorldEnv(),)),
            (sarsa_lambda, (GridWorldEnv(),)),
            (mc_control, (lambda: BlackjackEnv(),)),
            (mc_es_control, ()),
            (train_reinforce, (CartPoleEnv(),)),
        ]
        for fn, args in cases:
            with self.assertRaises(ValueError, msg=f"{fn.__name__} should reject episodes=0"):
                fn(*args, episodes=0)

    def test_negative_episodes_also_rejected(self):
        with self.assertRaises(ValueError):
            q_learning(GridWorldEnv(), episodes=-10)


if __name__ == "__main__":
    unittest.main()
