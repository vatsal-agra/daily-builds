"""Lookup correctness: the flagship property this whole engine rests on --
an iterative FIND_NODE/FIND_VALUE lookup run over a lossy, latent simulated
network converges to (very close to) the *true* k nearest nodes, verified
against an independent brute-force oracle that has global knowledge no
individual DHT node is given."""
import random
import unittest

from meridian import nodeid
from meridian.simulator import Simulation

def run_lookup(sim, src, target, find_value=False):
    box = {}
    if find_value:
        src.lookup_value(target, lambda value, contacts: box.update(value=value, contacts=contacts, done=True))
    else:
        src.lookup_nodes(target, lambda contacts: box.update(contacts=contacts, done=True))
    completed = sim.pump_until(lambda: box.get("done", False))
    assert completed, "lookup never completed"
    return box


class TestLookupAgainstOracle(unittest.TestCase):
    def _build_swarm(self, seed, n=40, loss_prob=0.05):
        sim = Simulation(seed=seed, loss_prob=loss_prob, k=20, alpha=3)
        nodes = sim.bootstrap_swarm(n)
        sim.run_until(n * 30 + 800)
        return sim, nodes

    def test_lookup_converges_to_true_closest_no_loss(self):
        sim, nodes = self._build_swarm(seed=1, loss_prob=0.0)
        r = random.Random(123)
        overlaps = []
        for _ in range(15):
            src = r.choice(sim.live_nodes())
            target = nodeid.random_id(r)
            box = run_lookup(sim, src, target)
            truth = set(sim.true_k_closest(target, 20))
            got = set(box.get("contacts", []))
            overlaps.append(len(truth & got) / len(truth))
        avg = sum(overlaps) / len(overlaps)
        # with zero loss and a settled network, lookups should find
        # essentially every one of the true closest nodes
        self.assertGreaterEqual(avg, 0.95, f"overlaps were {overlaps}")

    def test_lookup_still_mostly_works_with_realistic_loss(self):
        sim, nodes = self._build_swarm(seed=2, loss_prob=0.08)
        r = random.Random(456)
        overlaps = []
        for _ in range(15):
            src = r.choice(sim.live_nodes())
            target = nodeid.random_id(r)
            box = run_lookup(sim, src, target)
            truth = set(sim.true_k_closest(target, 20))
            got = set(box.get("contacts", []))
            overlaps.append(len(truth & got) / len(truth) if truth else 1.0)
        avg = sum(overlaps) / len(overlaps)
        self.assertGreaterEqual(avg, 0.75, f"overlaps were {overlaps}")

    def test_lookup_from_every_node_finds_a_specific_target(self):
        sim, nodes = self._build_swarm(seed=3, n=25, loss_prob=0.0)
        target_node = nodes[len(nodes) // 2]
        for src in nodes:
            if src.id == target_node.id:
                continue
            box = run_lookup(sim, src, target_node.id)
            self.assertIn(target_node.id, box["contacts"], f"{nodeid.short(src.id)} failed to find {nodeid.short(target_node.id)}")

    def test_find_value_locates_stored_value_from_a_different_node(self):
        sim, nodes = self._build_swarm(seed=4, n=25, loss_prob=0.0)
        publisher = nodes[0]
        key, value = b"lookup-test-key", b"lookup-test-value"
        put_box = {}
        publisher.put(key, value, on_complete=lambda ok, total: put_box.update(ok=ok, total=total, done=True))
        sim.pump_until(lambda: put_box.get("done", False))
        self.assertGreater(put_box["ok"], 0)

        key_id = nodeid.sha1_int(key)
        fetcher = nodes[-1]
        self.assertNotEqual(fetcher.id, publisher.id)
        box = run_lookup(sim, fetcher, key_id, find_value=True)
        self.assertEqual(box["value"], value)

    def test_lookup_of_own_id_returns_empty_or_self_excluded(self):
        sim, nodes = self._build_swarm(seed=5, n=10, loss_prob=0.0)
        src = nodes[0]
        box = run_lookup(sim, src, src.id)
        self.assertNotIn(src.id, box["contacts"])

    def test_deterministic_across_repeated_runs_same_seed(self):
        sim1, nodes1 = self._build_swarm(seed=42, n=20, loss_prob=0.1)
        sim2, nodes2 = self._build_swarm(seed=42, n=20, loss_prob=0.1)
        self.assertEqual([n.id for n in nodes1], [n.id for n in nodes2])
        target = 0xDEADBEEF
        box1 = run_lookup(sim1, sim1.nodes[nodes1[0].id], target)
        box2 = run_lookup(sim2, sim2.nodes[nodes2[0].id], target)
        self.assertEqual(box1["contacts"], box2["contacts"])
        self.assertEqual(sim1.network.stats, sim2.network.stats)


if __name__ == "__main__":
    unittest.main()
