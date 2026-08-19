import random
import unittest

from skein.oracle import OracleRGA
from skein.rga import CausalityError, RGA


class TestOracleAgreesWithTreeImpl(unittest.TestCase):
    """The oracle is a deliberately independent second implementation of
    the same spec (see oracle.py's docstring). These tests check it
    against the tree-based RGA across randomized op sets — this is the
    differential-testing backbone `convergence.py` relies on."""

    def test_agrees_on_many_random_sessions(self):
        for seed in range(30):
            src = RGA("src")
            rng = random.Random(seed)
            ops = []
            for _ in range(60):
                visible_len = len(src)
                if visible_len > 0 and rng.random() < 0.25:
                    op = src.local_delete(rng.randrange(visible_len))
                else:
                    pos = rng.randint(0, visible_len)
                    op = src.local_insert(pos, rng.choice("abcxyz "))
                ops.append(op)

            oracle = OracleRGA()
            for op in ops:
                oracle.apply(op)

            self.assertEqual(oracle.text, src.text, f"oracle disagreed with tree RGA for seed={seed}")

    def test_oracle_raises_on_causally_invalid_insert(self):
        src = RGA("src")
        ops = [src.local_insert(i, c) for i, c in enumerate("ab")]
        oracle = OracleRGA()
        with self.assertRaises(CausalityError):
            oracle.apply(ops[1])  # depends on ops[0] having already landed

    def test_oracle_raises_on_delete_before_insert(self):
        src = RGA("src")
        ins = src.local_insert(0, "x")
        deL = src.local_delete(0)
        oracle = OracleRGA()
        with self.assertRaises(CausalityError):
            oracle.apply(deL)
        oracle.apply(ins)
        oracle.apply(deL)  # now valid
        self.assertEqual(oracle.text, "")

    def test_oracle_idempotent_insert(self):
        src = RGA("src")
        op = src.local_insert(0, "x")
        oracle = OracleRGA()
        oracle.apply(op)
        oracle.apply(op)
        self.assertEqual(oracle.text, "x")


if __name__ == "__main__":
    unittest.main()
