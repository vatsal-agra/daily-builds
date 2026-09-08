import unittest

from meridian import nodeid
from meridian.simulator import Simulation


class TestBootstrapSwarm(unittest.TestCase):
    def test_creates_requested_node_count(self):
        sim = Simulation(seed=1)
        nodes = sim.bootstrap_swarm(15)
        self.assertEqual(len(nodes), 15)
        self.assertEqual(len(sim.nodes), 15)

    def test_all_nodes_eventually_live(self):
        sim = Simulation(seed=2)
        sim.bootstrap_swarm(10)
        sim.run_until(10 * 30 + 200)
        self.assertEqual(len(sim.live_nodes()), 10)

    def test_bootstrap_populates_routing_tables(self):
        sim = Simulation(seed=3, loss_prob=0.0)
        nodes = sim.bootstrap_swarm(20)
        sim.run_until(20 * 30 + 500)
        for n in nodes:
            self.assertGreater(
                n.routing_table.contact_count(), 0, f"node {nodeid.short(n.id)} never learned any peers"
            )

    def test_rejects_zero_nodes(self):
        sim = Simulation(seed=4)
        with self.assertRaises(ValueError):
            sim.bootstrap_swarm(0)

    def test_duplicate_node_id_rejected(self):
        sim = Simulation(seed=5)
        n = sim.create_node(node_id=123)
        with self.assertRaises(ValueError):
            sim.create_node(node_id=123)


class TestChurn(unittest.TestCase):
    def test_churn_reduces_live_count(self):
        sim = Simulation(seed=6, loss_prob=0.0)
        sim.bootstrap_swarm(30)
        sim.run_until(30 * 30 + 500)
        before = len(sim.live_nodes())
        ids = [n.id for n in sim.live_nodes()]
        sim.churn(ids, start=sim.network.time, end=sim.network.time + 2000, mean_interval=100)
        sim.run_until(sim.network.time + 2000)
        after = len(sim.live_nodes())
        self.assertLess(after, before)

    def test_churn_rejects_nonpositive_interval(self):
        sim = Simulation(seed=7)
        with self.assertRaises(ValueError):
            sim.churn([1, 2], 0, 100, mean_interval=0)

    def test_crash_events_are_logged(self):
        sim = Simulation(seed=8, loss_prob=0.0)
        sim.bootstrap_swarm(20)
        sim.run_until(20 * 30 + 500)
        ids = [n.id for n in sim.live_nodes()]
        sim.churn(ids, sim.network.time, sim.network.time + 3000, mean_interval=200)
        sim.run_until(sim.network.time + 3000)
        crash_events = [e for e in sim.trace if e["kind"] == "crash"]
        self.assertTrue(crash_events)


class TestOracle(unittest.TestCase):
    def test_true_k_closest_matches_manual_sort(self):
        sim = Simulation(seed=9)
        nodes = sim.bootstrap_swarm(25)
        sim.run_until(25 * 30 + 500)
        target = nodeid.random_id(sim.rng)
        got = sim.true_k_closest(target, 5)
        manual = sorted((n.id for n in nodes), key=lambda nid: nodeid.distance(target, nid))[:5]
        self.assertEqual(got, manual)

    def test_true_k_closest_excludes_dead_nodes_by_default(self):
        sim = Simulation(seed=10, loss_prob=0.0)
        nodes = sim.bootstrap_swarm(10)
        sim.run_until(10 * 30 + 200)
        victim = nodes[0]
        sim.network.set_live(victim.id, False)
        target = victim.id  # closest possible target to the dead node
        closest = sim.true_k_closest(target, 1)
        self.assertNotEqual(closest, [victim.id])

    def test_true_k_closest_can_include_dead_nodes_on_request(self):
        sim = Simulation(seed=11, loss_prob=0.0)
        nodes = sim.bootstrap_swarm(5)
        sim.run_until(5 * 30 + 200)
        victim = nodes[0]
        sim.network.set_live(victim.id, False)
        closest = sim.true_k_closest(victim.id, 1, live_only=False)
        self.assertEqual(closest, [victim.id])


class TestReproducibility(unittest.TestCase):
    def test_same_seed_produces_identical_node_ids(self):
        sim1 = Simulation(seed=999)
        sim2 = Simulation(seed=999)
        nodes1 = sim1.bootstrap_swarm(10)
        nodes2 = sim2.bootstrap_swarm(10)
        self.assertEqual([n.id for n in nodes1], [n.id for n in nodes2])

    def test_different_seeds_produce_different_swarms(self):
        sim1 = Simulation(seed=1)
        sim2 = Simulation(seed=2)
        nodes1 = sim1.bootstrap_swarm(10)
        nodes2 = sim2.bootstrap_swarm(10)
        self.assertNotEqual([n.id for n in nodes1], [n.id for n in nodes2])


if __name__ == "__main__":
    unittest.main()
