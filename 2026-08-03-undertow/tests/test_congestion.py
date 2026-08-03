import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from undertow.congestion import CONGESTION_AVOID, FAST_RECOVERY, RenoCongestionControl, SLOW_START


class TestRenoCongestionControl(unittest.TestCase):
    def test_starts_in_slow_start_at_one_mss(self):
        cc = RenoCongestionControl(mss=512)
        self.assertEqual(cc.state, SLOW_START)
        self.assertEqual(cc.cwnd, 512)

    def test_slow_start_grows_by_one_mss_per_ack(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=100)
        cc.on_new_ack(512)
        self.assertEqual(cc.cwnd, 1024)
        cc.on_new_ack(512)
        self.assertEqual(cc.cwnd, 1536)
        self.assertEqual(cc.state, SLOW_START)

    def test_transitions_to_congestion_avoidance_at_ssthresh(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=2)
        cc.on_new_ack(512)  # cwnd 512 -> 1024, still < ssthresh(1024)? equal -> switches
        self.assertEqual(cc.state, CONGESTION_AVOID)

    def test_congestion_avoidance_grows_sub_linearly_per_ack(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=1)
        # A fresh instance always starts in slow start regardless of
        # ssthresh (matches real TCP); the crossing is only checked when
        # an ACK actually grows cwnd past ssthresh.
        cc.on_new_ack(512)
        self.assertEqual(cc.state, CONGESTION_AVOID)
        before = cc.cwnd
        cc.on_new_ack(512)
        # In congestion avoidance a single ACK should grow cwnd by far less
        # than a full MSS (roughly mss^2/cwnd).
        self.assertLess(cc.cwnd - before, 512)
        self.assertGreater(cc.cwnd, before)

    def test_triple_duplicate_ack_triggers_fast_retransmit(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=100)
        cc.on_new_ack(512 * 20)  # build up cwnd
        cwnd_before = cc.cwnd
        self.assertIsNone(cc.on_duplicate_ack())
        self.assertIsNone(cc.on_duplicate_ack())
        result = cc.on_duplicate_ack()
        self.assertEqual(result, "fast_retransmit")
        self.assertEqual(cc.state, FAST_RECOVERY)
        self.assertEqual(cc.ssthresh, max(cwnd_before // 2, 2 * 512))
        self.assertEqual(cc.cwnd, cc.ssthresh + 3 * 512)

    def test_fast_recovery_inflates_then_deflates_to_ssthresh(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=100)
        cc.on_new_ack(512 * 20)
        cc.on_duplicate_ack()
        cc.on_duplicate_ack()
        cc.on_duplicate_ack()
        self.assertEqual(cc.state, FAST_RECOVERY)
        inflated = cc.cwnd
        cc.on_duplicate_ack()
        self.assertGreater(cc.cwnd, inflated)
        expected_ssthresh = cc.ssthresh
        cc.on_new_ack(512)  # the fresh ACK that ends recovery
        self.assertEqual(cc.state, CONGESTION_AVOID)
        self.assertEqual(cc.cwnd, expected_ssthresh)

    def test_timeout_resets_to_slow_start_at_one_mss(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=100)
        cc.on_new_ack(512 * 30)
        cwnd_before = cc.cwnd
        cc.on_timeout()
        self.assertEqual(cc.state, SLOW_START)
        self.assertEqual(cc.cwnd, 512)
        self.assertEqual(cc.ssthresh, max(cwnd_before // 2, 2 * 512))

    def test_new_ack_resets_duplicate_counter(self):
        cc = RenoCongestionControl(mss=512, init_ssthresh_segments=100)
        cc.on_new_ack(512)
        cc.on_duplicate_ack()
        cc.on_duplicate_ack()
        cc.on_new_ack(512)  # fresh data acked, streak should reset
        # If the streak hadn't reset, this would be the 3rd dup ACK
        # overall and would fire fast_retransmit here instead.
        self.assertIsNone(cc.on_duplicate_ack())
        self.assertIsNone(cc.on_duplicate_ack())
        self.assertEqual(cc.on_duplicate_ack(), "fast_retransmit")


if __name__ == "__main__":
    unittest.main()
