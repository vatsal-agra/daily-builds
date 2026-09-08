import random
import unittest

from meridian import nodeid
from meridian.dht import REPLICA_REPUBLISH_INTERVAL, REPUBLISH_INTERVAL, DHTNode, StoredEntry
from meridian.network import Network
from meridian.protocol import FindValueReq
from meridian.simulator import Simulation


def make_pair(loss_prob=0.0):
    net = Network(random.Random(0), loss_prob=loss_prob)
    a = DHTNode(0xA, net)
    b = DHTNode(0xB, net)
    net.set_live(a.id, True)
    net.set_live(b.id, True)
    return net, a, b


class TestLazyExpiration(unittest.TestCase):
    def test_expired_entry_is_not_returned_by_find_value(self):
        net, a, b = make_pair()
        b.storage[123] = StoredEntry(value=b"stale", expires_at=10, origin="owner", last_republished=0)
        net.run_until(20)
        result = {}
        a._rpc(
            b.id,
            lambda rid: FindValueReq(rid, a.id, 123),
            on_ok=lambda r: result.update(value=r.value),
            on_timeout=lambda: result.update(value="TIMEOUT"),
        )
        net.run_all()
        self.assertIsNone(result["value"])

    def test_unexpired_entry_is_returned(self):
        net, a, b = make_pair()
        b.storage[123] = StoredEntry(value=b"fresh", expires_at=1000, origin="owner", last_republished=0)
        net.run_until(20)
        result = {}
        a._rpc(
            b.id,
            lambda rid: FindValueReq(rid, a.id, 123),
            on_ok=lambda r: result.update(value=r.value),
            on_timeout=lambda: result.update(value="TIMEOUT"),
        )
        net.run_all()
        self.assertEqual(result["value"], b"fresh")


class TestProactivePurge(unittest.TestCase):
    def test_tick_maintenance_deletes_expired_storage(self):
        net = Network(random.Random(0))
        node = DHTNode(1, net)
        net.set_live(1, True)
        node.storage[42] = StoredEntry(value=b"x", expires_at=5, origin="replica", last_republished=0)
        net.run_until(10)
        self.assertIn(42, node.storage)
        node.tick_maintenance()
        self.assertNotIn(42, node.storage)

    def test_tick_maintenance_keeps_unexpired_storage(self):
        net = Network(random.Random(0))
        node = DHTNode(1, net)
        net.set_live(1, True)
        node.storage[42] = StoredEntry(value=b"x", expires_at=5000, origin="replica", last_republished=0)
        net.run_until(10)
        node.tick_maintenance()
        self.assertIn(42, node.storage)


class TestRepublish(unittest.TestCase):
    def test_value_survives_past_original_ttl_via_republish(self):
        sim = Simulation(seed=10, loss_prob=0.0, k=20, alpha=3)
        nodes = sim.bootstrap_swarm(20)  # bootstrap_swarm schedules maintenance for every node
        sim.run_until(20 * 30 + 500)

        publisher = nodes[0]
        key, value = b"long-lived-key", b"long-lived-value"
        put_box = {}
        publisher.put(key, value, on_complete=lambda ok, total: put_box.update(ok=ok, total=total))
        sim.run_until(sim.network.time + 3000)
        self.assertGreater(put_box["ok"], 0)

        # default TTL is 2000 ticks; run well past that -- if republish
        # weren't happening, every replica would have expired by now
        sim.run_until(sim.network.time + 6000)

        fetcher = nodes[-1]
        get_box = {}
        fetcher.get(key, lambda v: get_box.update(value=v))
        sim.run_until(sim.network.time + 3000)
        self.assertEqual(get_box["value"], value)

    def test_value_expires_without_maintenance(self):
        """Contrast case: build a swarm the same way but never schedule
        per-node maintenance, so nothing ever republishes. The initial
        replication still happens (that's a one-shot lookup+STORE, not
        maintenance), but with no republish the TTL clock just runs out."""
        sim = Simulation(seed=11, loss_prob=0.0, k=20, alpha=3)
        first = sim.create_node()
        sim.network.set_live(first.id, True)
        others = []
        for i in range(1, 15):
            n = sim.create_node()
            sim.join(n, first.id, delay=i * 30)
            others.append(n)
        sim.run_until(600)  # let everyone join, but no schedule_maintenance() calls anywhere

        publisher = first
        key, value = b"short-lived-key", b"short-lived-value"
        put_box = {}
        short_ttl = 400
        publisher.put(key, value, ttl=short_ttl, on_complete=lambda ok, total: put_box.update(ok=ok, total=total))
        sim.run_until(sim.network.time + 1000)
        self.assertGreater(put_box["ok"], 0)

        sim.run_until(sim.network.time + short_ttl + 2000)  # well past TTL, no republish ever ran

        fetcher = others[-1]
        get_box = {}
        fetcher.get(key, lambda v: get_box.update(value=v))
        sim.run_until(sim.network.time + 2000)
        self.assertIsNone(get_box["value"])

    def test_replica_holder_republishes_too(self):
        sim = Simulation(seed=12, loss_prob=0.0, k=20, alpha=3)
        nodes = sim.bootstrap_swarm(20)
        sim.run_until(20 * 30 + 500)

        publisher = nodes[0]
        key, value = b"replica-republish-key", b"v"
        key_id = nodeid.sha1_int(key)
        publisher.put(key, value, on_complete=lambda ok, total: None)
        sim.run_until(sim.network.time + 3000)

        holders = [n for n in nodes if n.id != publisher.id and key_id in n.storage]
        self.assertTrue(holders, "expected at least one replica holder besides the publisher")
        holder = holders[0]
        before = holder.storage[key_id].last_republished
        sim.run_until(sim.network.time + REPLICA_REPUBLISH_INTERVAL + 1500)
        # entry must still be present (not expired) and have been refreshed
        self.assertIn(key_id, holder.storage)
        self.assertGreater(holder.storage[key_id].last_republished, before)


if __name__ == "__main__":
    unittest.main()
