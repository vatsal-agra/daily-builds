import unittest

from conduit.congestion import (
    CONGESTION_AVOIDANCE,
    FAST_RECOVERY,
    SLOW_START,
    RenoCongestionControl,
)


class TestRenoCongestionControl(unittest.TestCase):
    def test_initial_state(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=2)
        self.assertEqual(cc.cwnd, 2000)
        self.assertEqual(cc.state, SLOW_START)

    def test_slow_start_grows_by_mss_per_ack(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=1, init_ssthresh_bytes=100_000)
        cc.on_new_ack(1000, send_una_after=2000)
        self.assertEqual(cc.cwnd, 2000)  # 1000 + 1000
        cc.on_new_ack(1000, send_una_after=3000)
        self.assertEqual(cc.cwnd, 3000)
        self.assertEqual(cc.state, SLOW_START)

    def test_transitions_to_congestion_avoidance_at_ssthresh(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=1, init_ssthresh_bytes=2500)
        cc.on_new_ack(1000, send_una_after=2000)  # cwnd 1000 -> 2000, still slow start
        self.assertEqual(cc.state, SLOW_START)
        cc.on_new_ack(1000, send_una_after=3000)  # cwnd 2000 -> 3000, crosses ssthresh
        self.assertEqual(cc.state, CONGESTION_AVOIDANCE)

    def test_congestion_avoidance_grows_sublinearly(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=10, init_ssthresh_bytes=1)
        cc.state = CONGESTION_AVOIDANCE
        cwnd_before = cc.cwnd
        cc.on_new_ack(1000, send_una_after=cwnd_before + 1000)
        # Additive increase: roughly +mss^2/cwnd per ACK, much less than +mss.
        self.assertGreater(cc.cwnd, cwnd_before)
        self.assertLess(cc.cwnd - cwnd_before, 1000)

    def test_triple_dup_ack_triggers_fast_retransmit(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=10)
        cwnd_before = cc.cwnd
        self.assertFalse(cc.on_duplicate_ack(send_next=50_000))
        self.assertFalse(cc.on_duplicate_ack(send_next=50_000))
        fast = cc.on_duplicate_ack(send_next=50_000)
        self.assertTrue(fast)
        self.assertEqual(cc.state, FAST_RECOVERY)
        self.assertEqual(cc.ssthresh, cwnd_before // 2)
        self.assertEqual(cc.cwnd, cc.ssthresh + 3 * cc.mss)

    def test_fast_recovery_inflates_on_further_dup_acks(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=10)
        cc.on_duplicate_ack(50_000)
        cc.on_duplicate_ack(50_000)
        cc.on_duplicate_ack(50_000)  # enters fast recovery
        cwnd_in_recovery = cc.cwnd
        cc.on_duplicate_ack(50_000)
        self.assertEqual(cc.cwnd, cwnd_in_recovery + cc.mss)

    def test_new_ack_covering_recovery_point_deflates_and_exits(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=10)
        cc.on_duplicate_ack(send_next=50_000)
        cc.on_duplicate_ack(send_next=50_000)
        cc.on_duplicate_ack(send_next=50_000)  # -> FAST_RECOVERY, recovery_point=50_000
        ssthresh_at_recovery = cc.ssthresh
        cc.on_new_ack(acked_bytes=5000, send_una_after=50_000)  # covers the recovery point
        self.assertEqual(cc.state, CONGESTION_AVOIDANCE)
        self.assertEqual(cc.cwnd, ssthresh_at_recovery)

    def test_partial_ack_in_recovery_inflates_without_exiting(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=10)
        cc.on_duplicate_ack(send_next=50_000)
        cc.on_duplicate_ack(send_next=50_000)
        cc.on_duplicate_ack(send_next=50_000)  # recovery_point = 50_000
        cwnd_before = cc.cwnd
        cc.on_new_ack(acked_bytes=1000, send_una_after=40_000)  # does not reach recovery point
        self.assertEqual(cc.state, FAST_RECOVERY)
        self.assertEqual(cc.cwnd, cwnd_before + 1000)

    def test_timeout_resets_to_slow_start(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=20)
        cwnd_before = cc.cwnd
        cc.on_timeout()
        self.assertEqual(cc.state, SLOW_START)
        self.assertEqual(cc.cwnd, cc.mss)
        self.assertEqual(cc.ssthresh, cwnd_before // 2)

    def test_ssthresh_never_below_two_segments(self):
        cc = RenoCongestionControl(mss=1000, init_cwnd_segments=1)  # cwnd = 1000
        cc.on_timeout()
        self.assertGreaterEqual(cc.ssthresh, 2 * cc.mss)


if __name__ == "__main__":
    unittest.main()
