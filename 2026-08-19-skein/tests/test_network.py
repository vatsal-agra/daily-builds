import unittest

from skein.network import SimNetwork
from skein.simulate import Simulation


class TestSimNetworkBasics(unittest.TestCase):
    def test_send_and_drain_delivers_to_every_other_site(self):
        net = SimNetwork(site_ids=["a", "b", "c"], seed=1, latency_range=(1, 1))
        net.send("a", "PAYLOAD")
        delivered = net.drain()
        dests = sorted(d for d, _ in delivered)
        self.assertEqual(dests, ["b", "c"])  # never delivered back to sender

    def test_drop_prob_1_drops_everything(self):
        net = SimNetwork(site_ids=["a", "b"], seed=1, drop_prob=1.0)
        net.send("a", "x")
        delivered = net.drain()
        self.assertEqual(delivered, [])
        self.assertEqual(net.stats["dropped"], 1)

    def test_dup_prob_1_duplicates_everything(self):
        net = SimNetwork(site_ids=["a", "b"], seed=1, dup_prob=1.0, latency_range=(1, 1))
        net.send("a", "x")
        delivered = net.drain()
        self.assertEqual(len(delivered), 2)
        self.assertEqual(net.stats["duplicated"], 1)

    def test_partition_blocks_send_in_both_directions(self):
        net = SimNetwork(site_ids=["a", "b"], seed=1)
        net.partition("b")
        net.send("a", "to-b")
        self.assertEqual(net.drain(), [])
        net.heal("b")
        net.send("b", "from-b")  # b itself was origin, also partitioned-checked, now healed
        self.assertEqual(len(net.drain()), 1)

    def test_is_partitioned_reflects_state(self):
        net = SimNetwork(site_ids=["a", "b"], seed=1)
        self.assertFalse(net.is_partitioned("a"))
        net.partition("a")
        self.assertTrue(net.is_partitioned("a"))
        net.heal("a")
        self.assertFalse(net.is_partitioned("a"))

    def test_resync_delivers_with_no_extra_delay(self):
        net = SimNetwork(site_ids=["a", "b"], seed=1, latency_range=(5, 10))
        net.resync("b", ["op1", "op2"])
        delivered = net.step()  # a single tick should be enough — no random delay applied
        self.assertEqual(sorted(op for _, op in delivered), ["op1", "op2"])


class TestPartitionIsolationRegression(unittest.TestCase):
    """Regression test for REVIEW.md bug #2: healing one site used to
    leak its edits to a still-partitioned third site."""

    def test_heal_does_not_leak_to_still_partitioned_site(self):
        sim = Simulation(["a", "b", "c"], seed=1)
        sim.type_str("a", 0, "hi")
        sim.drain()

        sim.partition("b")
        sim.partition("c")
        sim.type_str("a", 2, "!")
        sim.drain()

        sim.heal("b")  # only b reconnects
        sim.drain()

        self.assertEqual(sim.sites["b"].text, "hi!")
        self.assertEqual(sim.sites["c"].text, "hi", "c is still partitioned — it must not see a's edit yet")

        sim.heal("c")
        sim.drain()
        self.assertEqual(sim.sites["c"].text, "hi!")
        self.assertTrue(sim.converged())


if __name__ == "__main__":
    unittest.main()
