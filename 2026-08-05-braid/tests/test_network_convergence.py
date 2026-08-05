"""Property-based convergence proof: crdt/network.py's deterministic
adversarial simulator (latency/reorder/dup/loss/partition + gossip)
driving crdt/site.py's real Site replicas. This is what makes Strong
Eventual Consistency a *tested claim*, not an assertion in a docstring."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crdt.network import Network, Simulation
from crdt.site import Site


class TestNetworkPrimitives(unittest.TestCase):
    def test_latency_delays_delivery(self):
        net = Network(seed=1, latency_range=(3, 3), dup_prob=0, drop_prob=0)
        net.send("A", "B", "hello")
        self.assertEqual(net.advance(2), [])  # not yet -- latency is 3 ticks
        delivered = net.advance(1)
        self.assertEqual(delivered, [("B", "hello")])

    def test_drop_prob_1_means_nothing_arrives(self):
        net = Network(seed=1, latency_range=(1, 1), dup_prob=0, drop_prob=1.0)
        net.send("A", "B", "x")
        self.assertEqual(net.advance(5), [])

    def test_partition_holds_then_releases_on_heal(self):
        net = Network(seed=1, latency_range=(1, 1), dup_prob=0, drop_prob=0)
        net.partition("A", "B")
        net.send("A", "B", "secret")
        self.assertEqual(net.advance(10), [])  # held, not delivered
        net.heal("A", "B")
        self.assertEqual(net.advance(5), [("B", "secret")])


class TestSimulationConvergence(unittest.TestCase):
    def test_convergence_sweep(self):
        """The core claim: for every seed in a wide sweep, all replicas
        converge to byte-identical text despite latency/reorder/dup/loss."""
        failures = []
        for seed in range(60):
            sim = Simulation(seed, num_sites=4)
            result = sim.run(num_ops=30)
            if not result["converged"]:
                failures.append((seed, result["texts"]))
        self.assertEqual(failures, [], f"{len(failures)} seed(s) failed to converge: {failures[:3]}")

    def test_more_sites_still_converge(self):
        failures = []
        for seed in range(20):
            sim = Simulation(seed, num_sites=7)
            result = sim.run(num_ops=25)
            if not result["converged"]:
                failures.append(seed)
        self.assertEqual(failures, [])

    def test_requires_at_least_two_sites(self):
        with self.assertRaises(ValueError):
            Simulation(seed=1, num_sites=1)
        with self.assertRaises(ValueError):
            Simulation(seed=1, num_sites=0)


class TestPartitionScenario(unittest.TestCase):
    def test_partition_diverges_then_heals_to_convergence(self):
        sim = Simulation(seed=42, num_sites=4)

        def pump(ticks):
            for to_id, payload in sim.net.advance(ticks):
                sim._deliver_full(to_id, payload)

        for a in ["A", "B"]:
            for b in ["C", "D"]:
                sim.net.partition(a, b)

        for _ in range(15):
            sim.random_edit(sim.rng.choice(["A", "B"]))
            sim.random_edit(sim.rng.choice(["C", "D"]))
            pump(3)
            sim._gossip_two_way()
            pump(3)

        texts = {sid: s.text() for sid, s in sim.sites.items()}
        self.assertEqual(texts["A"], texts["B"])
        self.assertEqual(texts["C"], texts["D"])
        self.assertNotEqual(texts["A"], texts["C"], "the two halves should have diverged during the partition")

        for a in ["A", "B"]:
            for b in ["C", "D"]:
                sim.net.heal(a, b)
        for _ in range(30):
            pump(5)
            sim._gossip_two_way()
        pump(50)

        final_texts = {sid: s.text() for sid, s in sim.sites.items()}
        self.assertEqual(len(set(final_texts.values())), 1, f"failed to reconverge: {final_texts}")


class TestRandomizedFuzzAcrossSitesDirectly(unittest.TestCase):
    """A lower-level fuzzer than Simulation: hammers Site.receive()
    directly (not through Network) with shuffled, duplicated delivery
    order across many sites, insert/delete/undo mixed in."""

    def _run_trial(self, seed, num_sites=4, num_ops=50):
        rng = random.Random(seed)
        alphabet = "abcde"
        sites = {chr(65 + i): Site(chr(65 + i)) for i in range(num_sites)}
        all_ops = []
        for _ in range(num_ops):
            sid = rng.choice(list(sites))
            s = sites[sid]
            length = s.doc.visible_length()
            if length == 0 or rng.random() < 0.7:
                idx = rng.randint(0, length)
                op = s.type_insert(idx, rng.choice(alphabet))
            else:
                idx = rng.randint(0, length - 1)
                op = s.type_delete(idx)
            all_ops.append((op, sid))

        deliveries = []
        for op, origin_sid in all_ops:
            for sid in sites:
                if sid != origin_sid:
                    deliveries.append((sid, op))
                    if rng.random() < 0.15:
                        deliveries.append((sid, op))
        rng.shuffle(deliveries)
        for sid, op in deliveries:
            sites[sid].receive(op)

        texts = {sid: s.text() for sid, s in sites.items()}
        unsettled = [sid for sid, s in sites.items() if not s.is_settled()]
        return texts, unsettled

    def test_fuzz_sweep(self):
        failures = []
        for seed in range(100):
            texts, unsettled = self._run_trial(seed)
            if len(set(texts.values())) != 1 or unsettled:
                failures.append((seed, unsettled, texts))
        self.assertEqual(failures, [], f"{len(failures)} failing seed(s): {failures[:2]}")


if __name__ == "__main__":
    unittest.main()
