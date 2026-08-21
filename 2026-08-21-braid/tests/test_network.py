import unittest

from network.sim_network import SimNetwork


class TestSimNetwork(unittest.TestCase):
    def test_reliable_delivery_when_zero_chaos(self):
        net = SimNetwork(["a", "b"], seed=1, latency_range=(1, 1), loss_p=0.0, dup_p=0.0)
        received = []
        net.send("a", "b", {"payload": "x"})
        net.run_until_quiescent(lambda dst, op: received.append((dst, op)))
        self.assertEqual(received, [("b", {"payload": "x"})])

    def test_loss_actually_drops_messages(self):
        net = SimNetwork(["a", "b"], seed=1, latency_range=(1, 1), loss_p=1.0)
        received = []
        for _ in range(20):
            net.send("a", "b", {"n": 1})
        net.run_until_quiescent(lambda dst, op: received.append((dst, op)))
        self.assertEqual(received, [], "loss_p=1.0 should drop everything")

    def test_duplication_can_deliver_twice(self):
        net = SimNetwork(["a", "b"], seed=2, latency_range=(1, 2), loss_p=0.0, dup_p=1.0)
        received = []
        net.send("a", "b", {"n": 1})
        net.run_until_quiescent(lambda dst, op: received.append((dst, op)))
        self.assertEqual(len(received), 2, "dup_p=1.0 should always duplicate")

    def test_partition_blocks_then_heal_delivers(self):
        net = SimNetwork(["a", "b"], seed=3, latency_range=(1, 1), loss_p=0.0)
        net.partition(["a"], ["b"], ticks=5)
        received = []
        net.send("a", "b", {"n": 1})
        # step through the partition window -- nothing should arrive
        for _ in range(4):
            net.step(lambda dst, op: received.append((dst, op)))
        self.assertEqual(received, [], "message should be held, not delivered, during partition")
        # after enough ticks the partition heals on its own
        net.run_until_quiescent(lambda dst, op: received.append((dst, op)))
        self.assertEqual(len(received), 1, "message should be delivered once healed, not lost")

    def test_is_currently_partitioned(self):
        net = SimNetwork(["a", "b", "c"], seed=4)
        self.assertFalse(net.is_currently_partitioned("a"))
        net.partition(["a"], ["b", "c"], ticks=10)
        self.assertTrue(net.is_currently_partitioned("a"))
        self.assertTrue(net.is_currently_partitioned("b"))
        # a peer NOT named in the partition at all should read as unaffected
        net2 = SimNetwork(["a", "b", "c", "d"], seed=5)
        net2.partition(["a"], ["b"], ticks=10)
        self.assertFalse(net2.is_currently_partitioned("d"))

    def test_partition_expires_after_its_own_tick_window(self):
        net = SimNetwork(["a", "b"], seed=6)
        net.partition(["a"], ["b"], ticks=3)
        net.step(lambda d, o: None)
        net.step(lambda d, o: None)
        net.step(lambda d, o: None)
        self.assertFalse(net.is_currently_partitioned("a"), "partition should have expired by now")

    def test_never_quiesces_raises_instead_of_hanging(self):
        net = SimNetwork(["a", "b"], seed=7, latency_range=(1, 1))
        net.partition(["a"], ["b"], ticks=10**9)  # effectively permanent
        net.send("a", "b", {"n": 1})
        with self.assertRaises(RuntimeError):
            net.run_until_quiescent(lambda d, o: None, max_ticks=50)


if __name__ == "__main__":
    unittest.main()
