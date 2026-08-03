import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from undertow.rto import ALPHA, BETA, K, MAX_RTO, MIN_RTO, RTOEstimator


class TestRTOEstimator(unittest.TestCase):
    def test_first_sample_sets_srtt_and_rttvar(self):
        est = RTOEstimator()
        est.sample(0.5)
        self.assertAlmostEqual(est.srtt, 0.5)
        self.assertAlmostEqual(est.rttvar, 0.25)
        self.assertAlmostEqual(est.rto, 0.5 + 4 * 0.25)

    def test_second_sample_uses_jacobson_karels_formula(self):
        est = RTOEstimator()
        est.sample(0.5)
        est.sample(0.6)
        expected_rttvar = (1 - BETA) * 0.25 + BETA * abs(0.5 - 0.6)
        expected_srtt = (1 - ALPHA) * 0.5 + ALPHA * 0.6
        self.assertAlmostEqual(est.rttvar, expected_rttvar)
        self.assertAlmostEqual(est.srtt, expected_srtt)
        self.assertAlmostEqual(est.rto, expected_srtt + max(0.01, K * expected_rttvar))

    def test_rto_floored_at_min(self):
        est = RTOEstimator()
        for _ in range(20):
            est.sample(0.001)  # a tiny, stable RTT
        self.assertGreaterEqual(est.rto, MIN_RTO)

    def test_rto_capped_at_max(self):
        est = RTOEstimator()
        est.sample(100.0)
        self.assertLessEqual(est.rto, MAX_RTO)

    def test_backoff_doubles_and_caps(self):
        est = RTOEstimator()
        est.sample(0.2)
        before = est.current()
        est.backoff()
        self.assertAlmostEqual(est.rto, before * 2)
        for _ in range(20):
            est.backoff()
        self.assertLessEqual(est.rto, MAX_RTO)

    def test_stable_rtt_converges_to_near_that_rtt(self):
        est = RTOEstimator()
        for _ in range(50):
            est.sample(0.05)
        # RTTVAR shrinks to ~0 for a perfectly stable RTT, so RTO should
        # bottom out at the MIN_RTO floor rather than tracking SRTT down
        # to near zero.
        self.assertAlmostEqual(est.rto, MIN_RTO, places=3)

    def test_moderately_variable_rtt_settles_above_the_floor(self):
        est = RTOEstimator()
        for i in range(50):
            est.sample(0.3 if i % 2 == 0 else 0.1)  # oscillating RTT, mean 0.2
        self.assertGreater(est.rto, MIN_RTO)
        self.assertLess(est.rto, MAX_RTO)


if __name__ == "__main__":
    unittest.main()
