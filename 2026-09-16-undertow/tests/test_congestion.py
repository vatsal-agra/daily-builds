import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.congestion import RenoCongestionController


class TestRenoSlowStart(unittest.TestCase):
    def test_starts_at_one_mss(self):
        cc = RenoCongestionController(mss=1000)
        self.assertEqual(cc.cwnd, 1000)
        self.assertEqual(cc.state, "slow_start")

    def test_cwnd_doubles_per_rtt_in_slow_start(self):
        cc = RenoCongestionController(mss=1000)
        cc.ssthresh = 1_000_000  # keep it in slow start throughout
        cwnd_before = cc.cwnd
        # simulate one full RTT's worth of ACKs: cwnd/mss segments acked
        n_acks = cwnd_before // 1000
        for _ in range(n_acks):
            cc.on_new_ack(1000)
        # textbook slow start: cwnd approximately doubles per RTT
        self.assertAlmostEqual(cc.cwnd, cwnd_before * 2, delta=1000)

    def test_transitions_to_congestion_avoidance_at_ssthresh(self):
        cc = RenoCongestionController(mss=1000)
        cc.ssthresh = 3000
        while cc.state == "slow_start":
            cc.on_new_ack(1000)
        self.assertEqual(cc.state, "congestion_avoidance")
        self.assertGreaterEqual(cc.cwnd, cc.ssthresh)


class TestRenoCongestionAvoidance(unittest.TestCase):
    def test_growth_is_additive_not_multiplicative(self):
        cc = RenoCongestionController(mss=1000)
        cc.ssthresh = 1000
        cc.on_new_ack(1000)  # crosses into congestion avoidance
        self.assertEqual(cc.state, "congestion_avoidance")
        cwnd_before = cc.cwnd
        for _ in range(cwnd_before // 1000):
            cc.on_new_ack(1000)
        # additive increase: roughly +1 MSS per RTT, not exponential
        self.assertLess(cc.cwnd, cwnd_before * 1.5)
        self.assertGreater(cc.cwnd, cwnd_before)


class TestRenoFastRetransmit(unittest.TestCase):
    def test_three_dup_acks_trigger_fast_retransmit(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(5000)  # get some cwnd built up
        cwnd_before = cc.cwnd
        self.assertFalse(cc.on_dup_ack())
        self.assertFalse(cc.on_dup_ack())
        triggered = cc.on_dup_ack()
        self.assertTrue(triggered)
        self.assertEqual(cc.state, "fast_recovery")
        self.assertEqual(cc.ssthresh, max(cwnd_before // 2, 2000))
        self.assertEqual(cc.cwnd, cc.ssthresh + 3000)

    def test_fewer_than_three_dup_acks_does_not_trigger(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(5000)
        self.assertFalse(cc.on_dup_ack())
        self.assertFalse(cc.on_dup_ack())
        self.assertEqual(cc.state, "slow_start")

    def test_fast_recovery_inflates_window_per_extra_dup_ack(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(5000)
        cc.on_dup_ack()
        cc.on_dup_ack()
        cc.on_dup_ack()
        cwnd_in_recovery = cc.cwnd
        cc.on_dup_ack()
        self.assertEqual(cc.cwnd, cwnd_in_recovery + 1000)

    def test_new_ack_exits_fast_recovery_to_congestion_avoidance(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(5000)
        cc.on_dup_ack()
        cc.on_dup_ack()
        cc.on_dup_ack()
        ssthresh = cc.ssthresh
        cc.on_new_ack(1000)  # the retransmitted segment finally gets ACKed
        self.assertEqual(cc.state, "congestion_avoidance")
        self.assertEqual(cc.cwnd, ssthresh)


class TestRenoTimeout(unittest.TestCase):
    def test_timeout_halves_ssthresh_and_resets_to_one_mss(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(20000)
        cwnd_before = cc.cwnd
        cc.on_timeout()
        self.assertEqual(cc.ssthresh, max(cwnd_before // 2, 2000))
        self.assertEqual(cc.cwnd, 1000)
        self.assertEqual(cc.state, "slow_start")

    def test_repeated_timeouts_keep_halving_ssthresh_from_new_cwnd(self):
        cc = RenoCongestionController(mss=1000)
        cc.on_new_ack(50000)
        cc.on_timeout()
        first_ssthresh = cc.ssthresh
        cc.on_new_ack(cc.cwnd)  # grow a bit again before a second loss
        cc.on_timeout()
        self.assertLessEqual(cc.ssthresh, first_ssthresh)


if __name__ == "__main__":
    unittest.main()
