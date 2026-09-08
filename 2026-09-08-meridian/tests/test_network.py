import random
import unittest

from meridian.network import Network


class TestNetwork(unittest.TestCase):
    def test_rejects_bad_latency_range(self):
        with self.assertRaises(ValueError):
            Network(random.Random(0), latency_range=(0, 10))
        with self.assertRaises(ValueError):
            Network(random.Random(0), latency_range=(10, 5))

    def test_rejects_bad_loss_prob(self):
        with self.assertRaises(ValueError):
            Network(random.Random(0), loss_prob=1.0)
        with self.assertRaises(ValueError):
            Network(random.Random(0), loss_prob=-0.1)

    def test_offline_target_never_delivers(self):
        net = Network(random.Random(0), loss_prob=0.0)
        net.live.add(1)  # target 2 stays offline
        delivered = []
        net.send(1, 2, lambda: delivered.append(True))
        net.run_all()
        self.assertEqual(delivered, [])
        self.assertEqual(net.stats["dropped_offline"], 1)

    def test_live_target_with_zero_loss_always_delivers(self):
        net = Network(random.Random(0), loss_prob=0.0)
        net.live.update([1, 2])
        delivered = []
        for _ in range(100):
            net.send(1, 2, lambda: delivered.append(net.time))
        net.run_all()
        self.assertEqual(len(delivered), 100)
        self.assertEqual(net.stats["dropped_loss"], 0)

    def test_full_loss_drops_everything(self):
        net = Network(random.Random(0), loss_prob=0.999999)
        net.live.update([1, 2])
        delivered = []
        for _ in range(50):
            net.send(1, 2, lambda: delivered.append(True))
        net.run_all()
        self.assertEqual(delivered, [])

    def test_events_fire_in_time_order(self):
        net = Network(random.Random(1))
        order = []
        net.schedule_in(30, lambda: order.append("c"))
        net.schedule_in(10, lambda: order.append("a"))
        net.schedule_in(20, lambda: order.append("b"))
        net.run_all()
        self.assertEqual(order, ["a", "b", "c"])

    def test_run_until_stops_at_boundary(self):
        net = Network(random.Random(1))
        fired = []
        net.schedule_in(10, lambda: fired.append(1))
        net.schedule_in(20, lambda: fired.append(2))
        net.run_until(15)
        self.assertEqual(fired, [1])
        self.assertEqual(net.time, 15)
        net.run_until(25)
        self.assertEqual(fired, [1, 2])

    def test_deterministic_under_fixed_seed(self):
        def make_run():
            net = Network(random.Random(777), latency_range=(1, 100), loss_prob=0.3)
            net.live.update(range(10))
            log = []
            for i in range(200):
                target = i % 10
                net.send(0, target, (lambda t=target: log.append((net.time, t))))
            net.run_all()
            return log, dict(net.stats)

        log1, stats1 = make_run()
        log2, stats2 = make_run()
        self.assertEqual(log1, log2)
        self.assertEqual(stats1, stats2)

    def test_negative_delay_rejected(self):
        net = Network(random.Random(0))
        with self.assertRaises(ValueError):
            net.schedule_in(-1, lambda: None)

    def test_run_all_safety_limit(self):
        net = Network(random.Random(0))

        def reschedule():
            net.schedule_in(1, reschedule)

        net.schedule_in(1, reschedule)
        with self.assertRaises(RuntimeError):
            net.run_all(safety_limit=100)


if __name__ == "__main__":
    unittest.main()
