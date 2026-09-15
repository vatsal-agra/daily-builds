import unittest

from causeway.connection import RttEstimator


class TestRttEstimator(unittest.TestCase):
    def test_first_sample_seeds_srtt_and_half_rttvar(self):
        e = RttEstimator(min_rto=0.0, max_rto=100.0)
        e.sample(0.1)
        self.assertAlmostEqual(e.srtt, 0.1)
        self.assertAlmostEqual(e.rttvar, 0.05)
        self.assertAlmostEqual(e.rto, 0.1 + max(e.g, 4 * 0.05))

    def test_jacobson_karels_formula_matches_hand_computation(self):
        e = RttEstimator(min_rto=0.0, max_rto=100.0, clock_granularity=0.0)
        e.sample(0.1)
        srtt, rttvar = 0.1, 0.05
        e.sample(0.2)
        rttvar = (1 - 0.25) * rttvar + 0.25 * abs(srtt - 0.2)
        srtt = (1 - 0.125) * srtt + 0.125 * 0.2
        self.assertAlmostEqual(e.srtt, srtt)
        self.assertAlmostEqual(e.rttvar, rttvar)
        self.assertAlmostEqual(e.rto, srtt + 4 * rttvar)

    def test_stable_rtt_converges_rto_close_to_rtt(self):
        e = RttEstimator(min_rto=0.0, max_rto=100.0)
        for _ in range(200):
            e.sample(0.05)
        self.assertLess(e.rto, 0.1)
        self.assertAlmostEqual(e.srtt, 0.05, places=3)

    def test_jittery_rtt_inflates_rto_above_mean(self):
        stable = RttEstimator(min_rto=0.0, max_rto=100.0)
        jittery = RttEstimator(min_rto=0.0, max_rto=100.0)
        import random
        rng = random.Random(0)
        for _ in range(500):
            stable.sample(0.05)
            jittery.sample(max(0.001, 0.05 + rng.uniform(-0.04, 0.04)))
        self.assertGreater(jittery.rto, stable.rto)

    def test_rto_clamped_to_bounds(self):
        e = RttEstimator(min_rto=0.5, max_rto=1.0)
        e.sample(0.001)
        self.assertGreaterEqual(e.rto, 0.5)
        e2 = RttEstimator(min_rto=0.5, max_rto=1.0)
        e2.sample(10.0)
        self.assertLessEqual(e2.rto, 1.0)


if __name__ == "__main__":
    unittest.main()
