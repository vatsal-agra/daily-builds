import random
import unittest

from meridian import nodeid
from meridian.dht import DHTNode
from meridian.network import Network
from meridian.protocol import PingReq, StoreReq


def make_pair(seed=0, loss_prob=0.0, latency_range=(1, 5), k=20):
    net = Network(random.Random(seed), latency_range=latency_range, loss_prob=loss_prob)
    a = DHTNode(0xA, net, k=k)
    b = DHTNode(0xB, net, k=k)
    net.set_live(a.id, True)
    net.set_live(b.id, True)
    return net, a, b


class TestPing(unittest.TestCase):
    def test_ping_gets_pong_and_records_contact(self):
        net, a, b = make_pair()
        result = {}
        a._rpc(
            b.id,
            lambda rid: PingReq(rid, a.id),
            on_ok=lambda resp: result.update(ok=True, sender=resp.sender_id),
            on_timeout=lambda: result.update(ok=False),
        )
        net.run_all()
        self.assertTrue(result["ok"])
        self.assertEqual(result["sender"], b.id)
        # a PING/PONG round trip must feed both sides' routing tables
        a_bucket = a.routing_table.buckets[nodeid.bucket_index(a.id, b.id)]
        b_bucket = b.routing_table.buckets[nodeid.bucket_index(b.id, a.id)]
        self.assertIn(b.id, a_bucket.all_ids())
        self.assertIn(a.id, b_bucket.all_ids())

    def test_ping_to_offline_node_times_out(self):
        net, a, b = make_pair()
        net.set_live(b.id, False)
        result = {}
        a._rpc(b.id, lambda rid: PingReq(rid, a.id), on_ok=lambda r: result.update(ok=True), on_timeout=lambda: result.update(ok=False))
        net.run_all()
        self.assertEqual(result, {"ok": False})


class TestFindNode(unittest.TestCase):
    def test_find_node_returns_closest_known_contacts(self):
        net, a, b = make_pair(k=20)
        c = DHTNode(0xC, net, k=20)
        net.set_live(c.id, True)
        # a must know about b to route through it, and b must know about c
        # to be able to report it back
        a.record_contact(b.id)
        b.record_contact(c.id)
        net.run_all()

        result = {}
        a.lookup_nodes(0xC, lambda contacts: result.update(contacts=contacts))
        net.run_all()
        self.assertIn(c.id, result["contacts"])


class TestStoreAndFindValue(unittest.TestCase):
    def test_store_then_find_value_round_trip(self):
        net, a, b = make_pair()
        stored = {}
        a._rpc(
            b.id,
            lambda rid: StoreReq(rid, a.id, key=999, value=b"payload", ttl=1000),
            on_ok=lambda r: stored.update(ok=r.ok),
            on_timeout=lambda: stored.update(ok=False),
        )
        net.run_all()
        self.assertTrue(stored["ok"])
        self.assertEqual(b.storage[999].value, b"payload")

    def test_get_returns_none_for_unknown_key(self):
        net, a, b = make_pair()
        b.record_contact(a.id)  # give a something to route through
        a.record_contact(b.id)
        result = {}
        a.get(b"never stored", lambda v: result.update(value=v))
        net.run_all()
        self.assertIsNone(result["value"])


class TestLookupTracing(unittest.TestCase):
    """A DHTNode records trace events via its `_trace` callback; internal
    housekeeping lookups (bucket refresh, republish) pass trace=False so
    they don't flood a replay/trace log with per-hop noise from routine
    background activity. Confirms the on/off switch actually works at the
    Lookup level, independent of the CLI-level test that checks the same
    thing end to end through tick_maintenance()."""

    def test_traced_lookup_emits_start_and_done_events(self):
        events = []
        net = Network(random.Random(0), loss_prob=0.0)
        a = DHTNode(0xA, net, trace=lambda kind, **f: events.append(kind))
        b = DHTNode(0xB, net)
        net.set_live(a.id, True)
        net.set_live(b.id, True)
        a.record_contact(b.id)
        a.lookup_nodes(0xB, lambda contacts: None, trace=True)
        net.run_all()
        self.assertIn("lookup_start", events)
        self.assertIn("lookup_done", events)

    def test_untraced_lookup_emits_nothing(self):
        events = []
        net = Network(random.Random(0), loss_prob=0.0)
        a = DHTNode(0xA, net, trace=lambda kind, **f: events.append(kind))
        b = DHTNode(0xB, net)
        net.set_live(a.id, True)
        net.set_live(b.id, True)
        a.record_contact(b.id)
        a.lookup_nodes(0xB, lambda contacts: None, trace=False)
        net.run_all()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
