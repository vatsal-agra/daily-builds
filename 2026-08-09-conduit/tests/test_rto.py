import unittest

from conduit.rto import INITIAL_RTO, MAX_RTO, MIN_RTO, RTOEstimator


class TestRTOEstimator(unittest.TestCase):
    def test_initial_rto(self):
        est = RTOEstimator()
        self.assertEqual(est.rto, INITIAL_RTO)
        self.assertIsNone(est.srtt)

    def test_first_sample_sets_srtt_and_rttvar_per_rfc6298(self):
        est = RTOEstimator()
        est.sample(0.1)
        self.assertAlmostEqual(est.srtt, 0.1)
        self.assertAlmostEqual(est.rttvar, 0.05)  # R/2
        self.assertAlmostEqual(est.rto, 0.1 + 4 * 0.05)  # SRTT + 4*RTTVAR = 0.3
        self.assertEqual(est.samples, 1)

    def test_subsequent_sample_uses_ewma(self):
        est = RTOEstimator()
        est.sample(0.1)
        est.sample(0.1)  # a second identical sample shouldn't move SRTT
        self.assertAlmostEqual(est.srtt, 0.1, places=6)
        self.assertLess(est.rttvar, 0.05)  # variance shrinks toward 0 with agreeing samples

    def test_rto_floor_and_ceiling(self):
        est = RTOEstimator()
        est.sample(1e-9)  # absurdly small RTT
        self.assertGreaterEqual(est.rto, MIN_RTO)
        est2 = RTOEstimator()
        est2.sample(1000.0)  # absurdly large RTT
        self.assertLessEqual(est2.rto, MAX_RTO)

    def test_backoff_doubles_and_does_not_touch_srtt(self):
        est = RTOEstimator()
        est.sample(0.1)
        srtt_before = est.srtt
        rto_before = est.rto
        new_rto = est.backoff()
        self.assertAlmostEqual(new_rto, min(MAX_RTO, rto_before * 2))
        self.assertEqual(est.srtt, srtt_before)  # Karn's algorithm: backoff is SRTT-neutral

    def test_backoff_caps_at_max_rto(self):
        est = RTOEstimator()
        for _ in range(20):
            est.backoff()
        self.assertLessEqual(est.rto, MAX_RTO)

    def test_variance_grows_with_jitter(self):
        est = RTOEstimator()
        est.sample(0.1)
        est.sample(0.5)  # a very different sample should widen RTTVAR
        self.assertGreater(est.rttvar, 0.05)


if __name__ == "__main__":
    unittest.main()
