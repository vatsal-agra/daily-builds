"""Regression test embedding the stretch-feature #5 differential fuzz
harness into the permanent suite: a handful of seeds run on every test
pass, the full 60k-operation sweep is available via `python3 fuzz.py`."""
import unittest
import _pathsetup  # noqa: F401

from order import reset_id_counter
from fuzz import run_trial


class TestOracleAgreement(unittest.TestCase):
    def test_real_engine_matches_naive_oracle_across_seeds(self):
        for seed in range(15):
            reset_id_counter()
            failure = run_trial(n_ops=120, seed=seed)
            self.assertIsNone(failure, f"seed={seed}: {failure}")


if __name__ == "__main__":
    unittest.main()
