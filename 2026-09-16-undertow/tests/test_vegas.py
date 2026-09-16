import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.vegas import VegasCongestionController


class TestVegasRTTTracking(unittest.TestCase):
    def test_base_rtt_tracks_the_minimum_observed(self):
        cc = VegasCongestionController(mss=1000)
        cc.on_rtt_sample(0.05)
        cc.on_rtt_sample(0.03)
        cc.on_rtt_sample(0.08)
        self.assertAlmostEqual(cc.base_rtt, 0.03)

    def test_no_rtt_sample_yet_behaves_like_slow_start(self):
        cc = VegasCongestionController(mss=1000)
        before = cc.cwnd
        cc.on_new_ack(1000)
        self.assertEqual(cc.cwnd, before + 1000)


class TestVegasDelaySignal(unittest.TestCase):
    def test_stable_low_rtt_keeps_growing_in_slow_start(self):
        cc = VegasCongestionController(mss=1000, gamma=1.0)
        cc.on_rtt_sample(0.05)  # sets base_rtt
        cwnd_before = cc.cwnd
        cc.on_rtt_sample(0.05)  # same RTT again -> no queueing signal
        cc.on_new_ack(1000)
        self.assertGreater(cc.cwnd, cwnd_before)
        self.assertEqual(cc.state, "slow_start")

    def test_rising_rtt_exits_slow_start_before_any_loss(self):
        cc = VegasCongestionController(mss=1000, gamma=1.0)
        cc.on_rtt_sample(0.02)  # base_rtt
        # grow cwnd a bit first so the queueing estimate has something to bite on
        for _ in range(4):
            cc.on_new_ack(1000)
        cwnd_before_signal = cc.cwnd
        # RTT roughly doubles: a real queue has formed, well before any drop
        cc.on_rtt_sample(0.045)
        cc.on_new_ack(1000)
        self.assertEqual(cc.state, "congestion_avoidance")
        # exiting slow start on a delay signal, not a loss, must not slash cwnd
        self.assertGreaterEqual(cc.cwnd, cwnd_before_signal)

    def test_congestion_avoidance_backs_off_when_queue_exceeds_beta(self):
        cc = VegasCongestionController(mss=1000, alpha=2, beta=4, gamma=1)
        cc.on_rtt_sample(0.02)
        cc.state = "congestion_avoidance"
        cc._cwnd = 20_000  # 20 segments
        cwnd_before = cc.cwnd
        # rtt far above base_rtt -> a large queued-segments estimate, > beta
        cc.on_rtt_sample(0.2)
        cc.on_new_ack(1000)
        self.assertLess(cc.cwnd, cwnd_before)

    def test_congestion_avoidance_holds_steady_in_target_range(self):
        cc = VegasCongestionController(mss=1000, alpha=2, beta=4, gamma=1)
        cc.on_rtt_sample(0.02)
        cc.state = "congestion_avoidance"
        cc._cwnd = 20_000
        # queued = 20 * (1 - 0.02/rtt); pick rtt so queued lands between alpha and beta
        # queued=3 -> 1 - 0.02/rtt = 3/20 = 0.15 -> rtt = 0.02/0.85
        rtt = 0.02 / 0.85
        cc.on_rtt_sample(rtt)
        cwnd_before = cc.cwnd
        cc.on_new_ack(1000)
        self.assertEqual(cc.cwnd, cwnd_before)


class TestVegasLossHandling(unittest.TestCase):
    def test_still_responds_to_real_loss_like_reno(self):
        # Vegas backs off *earlier* on delay, but must still handle actual
        # loss correctly if it happens (dup acks / timeout), since a
        # real network can drop packets for reasons unrelated to queueing.
        cc = VegasCongestionController(mss=1000)
        cc.on_rtt_sample(0.02)
        cc.on_new_ack(5000)
        cwnd_before = cc.cwnd
        self.assertFalse(cc.on_dup_ack())
        self.assertFalse(cc.on_dup_ack())
        self.assertTrue(cc.on_dup_ack())
        self.assertEqual(cc.state, "fast_recovery")
        self.assertEqual(cc.ssthresh, max(cwnd_before // 2, 2000))

    def test_timeout_resets_to_slow_start(self):
        cc = VegasCongestionController(mss=1000)
        cc.on_rtt_sample(0.02)
        cc.on_new_ack(10_000)
        cc.on_timeout()
        self.assertEqual(cc.cwnd, 1000)
        self.assertEqual(cc.state, "slow_start")


if __name__ == "__main__":
    unittest.main()
