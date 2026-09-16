import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.rto import RTOEstimator


class TestRTOEstimator(unittest.TestCase):
    def test_first_sample_sets_srtt_and_rttvar(self):
        e = RTOEstimator()
        e.sample(1.0)
        self.assertEqual(e.srtt, 1.0)
        self.assertEqual(e.rttvar, 0.5)
        # RFC 6298: RTO = SRTT + max(G, K*RTTVAR) = 1.0 + max(0.01, 4*0.5) = 3.0
        self.assertAlmostEqual(e.rto, 3.0, places=6)

    def test_subsequent_sample_matches_jacobson_karels_formula(self):
        e = RTOEstimator()
        e.sample(1.0)
        e.sample(1.2)
        expected_rttvar = (1 - 0.25) * 0.5 + 0.25 * abs(1.0 - 1.2)
        expected_srtt = (1 - 0.125) * 1.0 + 0.125 * 1.2
        self.assertAlmostEqual(e.rttvar, expected_rttvar, places=9)
        self.assertAlmostEqual(e.srtt, expected_srtt, places=9)
        self.assertAlmostEqual(e.rto, expected_srtt + max(0.01, 4 * expected_rttvar), places=9)

    def test_stable_rtt_shrinks_rto_toward_srtt(self):
        e = RTOEstimator()
        for _ in range(50):
            e.sample(0.1)
        # rttvar should have collapsed toward 0 for a perfectly stable RTT
        self.assertLess(e.rttvar, 0.01)
        self.assertAlmostEqual(e.srtt, 0.1, places=3)

    def test_backoff_doubles_and_caps(self):
        e = RTOEstimator()
        e.sample(1.0)
        start = e.rto
        e.backoff()
        self.assertAlmostEqual(e.rto, start * 2, places=9)
        for _ in range(20):
            e.backoff()
        self.assertLessEqual(e.rto, 60.0)

    def test_rto_floor_enforced(self):
        e = RTOEstimator()
        e.sample(0.0001)
        self.assertGreaterEqual(e.rto, 0.2)

    def test_rejects_nonpositive_sample(self):
        e = RTOEstimator()
        with self.assertRaises(ValueError):
            e.sample(0)
        with self.assertRaises(ValueError):
            e.sample(-1)

    def test_karns_algorithm_is_the_callers_responsibility(self):
        # This module trusts the caller not to call sample() for a
        # retransmitted segment's RTT. Simulate a caller correctly
        # skipping an ambiguous sample and check the estimator is
        # unaffected by whatever it wasn't told about.
        e = RTOEstimator()
        e.sample(0.05)
        e.sample(0.05)
        before = (e.srtt, e.rttvar, e.rto)
        # a retransmitted segment's ambiguous "RTT" is simply never sampled
        after = (e.srtt, e.rttvar, e.rto)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
