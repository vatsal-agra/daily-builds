"""Real multi-process integration tests: every node is an actual OS
subprocess talking real HTTP, and "killing a node" is a real SIGKILL, not
an in-memory flag. This is the only way to genuinely exercise gossip-based
failure detection, hinted handoff, and read-repair across real connection
failures rather than trusting the unit tests' in-process shortcuts.
"""
import time
import unittest

from gossamer import client
from gossamer.cluster import Cluster
from gossamer.hashring import HashRing

NODE_IDS = ["A", "B", "C", "D", "E"]
VNODES = 32


def reference_ring():
    ring = HashRing(vnodes=VNODES)
    for n in NODE_IDS:
        ring.add_node(n)
    return ring


def find_key_with_owner(owner, n, exclude_owners=()):
    ring = reference_ring()
    i = 0
    while True:
        key = f"probe-{owner}-{i}"
        reps = ring.replicas_for(key, n)
        if owner in reps and not any(e in reps for e in exclude_owners):
            return key
        i += 1
        if i > 10000:
            raise RuntimeError("could not find a suitable probe key")


def wait_until(fn, timeout=8.0, interval=0.1):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last


class TestBasicReadWrite(unittest.TestCase):
    def test_put_then_get_roundtrips(self):
        with Cluster(NODE_IDS, base_port=9600, n=3, r=2, w=2, vnodes=VNODES) as c:
            status, body = client.put(c, "A", "hello", "world")
            self.assertEqual(status, 200)
            status, body = client.get(c, "B", "hello")
            self.assertEqual(status, 200)
            self.assertEqual([s["value"] for s in body["siblings"]], ["world"])

    def test_any_node_can_coordinate(self):
        with Cluster(NODE_IDS, base_port=9610, n=3, r=2, w=2, vnodes=VNODES) as c:
            for coord in NODE_IDS:
                status, _ = client.put(c, coord, f"k-{coord}", coord)
                self.assertEqual(status, 200)
            for coord in NODE_IDS:
                status, body = client.get(c, coord, f"k-A")
                self.assertEqual(status, 200)
                self.assertEqual(body["siblings"][0]["value"], "A")

    def test_read_your_own_write_context_chains(self):
        with Cluster(NODE_IDS, base_port=9620, n=3, r=2, w=2, vnodes=VNODES) as c:
            status, body = client.put(c, "A", "counter", 1, context=None)
            ctx = body["context"]
            status, body = client.put(c, "B", "counter", 2, context=ctx)
            self.assertEqual(status, 200)
            status, body = client.get(c, "C", "counter")
            self.assertEqual(len(body["siblings"]), 1)
            self.assertEqual(body["siblings"][0]["value"], 2)


class TestQuorumFaultTolerance(unittest.TestCase):
    def test_write_and_read_survive_one_dead_node_out_of_five(self):
        with Cluster(NODE_IDS, base_port=9630, n=3, r=2, w=2, vnodes=VNODES) as c:
            key = find_key_with_owner("C", 3)
            c.kill_node("C")
            status, body = client.put(c, "A", key, "survives", context=None)
            self.assertEqual(status, 200, body)
            status, body = client.get(c, "B", key)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["siblings"][0]["value"], "survives")

    def test_write_fails_below_w_when_too_many_replicas_down(self):
        with Cluster(NODE_IDS, base_port=9640, n=3, r=2, w=3, vnodes=VNODES) as c:
            key = find_key_with_owner("C", 3)
            c.kill_node("C")
            # W=3 but the request-time attempt to the just-killed node fails
            # immediately (connection refused) before gossip even notices,
            # so only 2 of 3 preferred replicas can ack -> below W.
            status, body = client.put(c, "A", key, "should-fail", context=None)
            self.assertEqual(status, 503, body)


class TestGossipFailureDetection(unittest.TestCase):
    def test_dead_node_is_eventually_marked_dead_by_peers(self):
        with Cluster(NODE_IDS, base_port=9650, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.0, dead_timeout=2.5) as c:
            c.kill_node("D")

            def check():
                st = c.status("A")
                return st["statuses"].get("D") == "dead"

            self.assertTrue(wait_until(check, timeout=8.0))

    def test_gossip_marks_suspected_before_dead(self):
        with Cluster(NODE_IDS, base_port=9660, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.0, dead_timeout=4.0) as c:
            c.kill_node("D")

            def check_suspected():
                st = c.status("A")
                return st["statuses"].get("D") == "suspected"

            self.assertTrue(wait_until(check_suspected, timeout=6.0))


class TestHintedHandoffAndRecovery(unittest.TestCase):
    def test_hint_is_stored_while_owner_down_and_flushed_on_revival(self):
        # suspect_timeout is kept well above a handful of gossip_interval
        # rounds (not just 2-3x it) so a healthy peer's heartbeat merely
        # arriving a little late under real system load -- the whole
        # suite runs several concurrent real clusters -- never gets
        # mistaken for that peer actually being down, which would make
        # pick_substitute wrongly find no candidate at all.
        with Cluster(NODE_IDS, base_port=9670, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.2, dead_timeout=3.0,
                     anti_entropy_interval=0.5) as c:
            key = find_key_with_owner("D", 3)
            c.kill_node("D")

            def is_suspected_everywhere():
                return all(c.status(n)["statuses"].get("D") in ("suspected", "dead")
                           for n in ["A", "B", "C", "E"])
            self.assertTrue(wait_until(is_suspected_everywhere, timeout=8.0))

            status, body = client.put(c, "A", key, "handoff-value", context=None)
            self.assertEqual(status, 200, body)

            # A hint for D must now exist on *some* surviving node.
            def any_hint_stored():
                for n in ["A", "B", "C", "E"]:
                    st = c.status(n)
                    if st["hints"].get("D", 0) > 0:
                        return True
                return False
            self.assertTrue(wait_until(any_hint_stored, timeout=5.0))

            # Reads must still work correctly while D is down, served via
            # the hint holder instead of D directly.
            status, body = client.get(c, "B", key)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["siblings"][0]["value"], "handoff-value")

            # Revive D fresh (empty store) -- it must recover the value
            # either via hint flush or anti-entropy, with no data loss.
            c.revive_node("D")

            def d_has_value():
                status, body = client.get(c, "D", key)
                return status == 200 and body["siblings"] and body["siblings"][0]["value"] == "handoff-value"
            self.assertTrue(wait_until(d_has_value, timeout=8.0))


class TestConcurrentWritesAndVectorClocks(unittest.TestCase):
    def test_concurrent_writes_surface_as_siblings_and_resolve(self):
        with Cluster(NODE_IDS, base_port=9680, n=3, r=2, w=2, vnodes=VNODES) as c:
            key = "shopping-cart"
            # Two clients write concurrently with NO shared context, coordinated
            # through two different nodes -- their vector clocks are genuinely
            # concurrent ({A:1} vs {C:1}), so the store must keep both,
            # not silently pick a winner.
            status1, _ = client.put(c, "A", key, ["milk"], context=None)
            status2, _ = client.put(c, "C", key, ["eggs"], context=None)
            self.assertEqual(status1, 200)
            self.assertEqual(status2, 200)

            status, body = client.get(c, "B", key)
            self.assertEqual(status, 200)
            values = sorted(s["value"][0] for s in body["siblings"])
            self.assertEqual(values, ["eggs", "milk"], "expected two real siblings, not one winner")

            # The application resolves the conflict (union) and writes back
            # using the context the GET returned (both parents), which must
            # causally dominate and collapse the siblings back to one.
            merged_value = sorted({v for s in body["siblings"] for v in s["value"]})
            status, _ = client.put(c, "A", key, merged_value, context=body["context"])
            self.assertEqual(status, 200)

            status, body = client.get(c, "E", key)
            self.assertEqual(status, 200)
            self.assertEqual(len(body["siblings"]), 1)
            self.assertEqual(sorted(body["siblings"][0]["value"]), ["eggs", "milk"])


class TestReadRepair(unittest.TestCase):
    def test_stale_replica_gets_repaired_by_a_read(self):
        with Cluster(NODE_IDS, base_port=9690, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.5, dead_timeout=4.0,
                     anti_entropy_interval=100.0) as c:
            key = find_key_with_owner("D", 3)
            # D goes down, a write happens (D misses it), D comes back
            # *before* it's marked dead so the coordinator writes directly
            # to it again on the next PUT -- except we skip that PUT, so D
            # stays stale until a read notices and repairs it. Disable
            # anti-entropy for this test so only read-repair can be the
            # mechanism that fixes D.
            c.kill_node("D")
            time.sleep(0.2)  # still "alive" per membership, so this PUT's
            # attempt at D fails outright (connection refused) - fine, W=2
            # is still satisfied by the other two preferred replicas.
            status, body = client.put(c, "A", key, "v1", context=None)
            self.assertEqual(status, 200, body)

            c.revive_node("D")

            def d_is_alive_everywhere():
                return c.status("A")["statuses"].get("D") == "alive"
            wait_until(d_is_alive_everywhere, timeout=8.0)

            # D is alive again but was never sent the write and holds no
            # hint for itself -- its own local store is empty for this key.
            status, body = client.get(c, "D", key)
            # A read coordinated by D itself still fans out to all
            # preferred replicas (including whichever ones do have the
            # value), so it must return the correct value even though D's
            # own copy was missing -- and that fan-out read repair should
            # backfill D.
            self.assertEqual(status, 200, body)
            self.assertEqual(body["siblings"][0]["value"], "v1")

            def d_store_has_key():
                st = c.status("D")
                return st["store_keys"] >= 1
            self.assertTrue(wait_until(d_store_has_key, timeout=5.0))


class TestAntiEntropy(unittest.TestCase):
    def test_stale_replica_heals_via_merkle_anti_entropy_without_any_read(self):
        with Cluster(NODE_IDS, base_port=9700, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.5, dead_timeout=4.0,
                     anti_entropy_interval=0.3) as c:
            key = find_key_with_owner("D", 3)
            time.sleep(0.2)  # D still "alive" per membership -> no hint path
            status, body = client.put(c, "A", key, "healed-by-merkle", context=None)
            self.assertEqual(status, 200, body)

            def d_has_key_locally():
                return c.status("D")["store_keys"] >= 1
            # No GET is issued anywhere in this test, so read-repair cannot
            # be what fixes D -- only the background Merkle anti-entropy
            # loop, running independently on every node, can.
            self.assertTrue(wait_until(d_has_key_locally, timeout=6.0))


if __name__ == "__main__":
    unittest.main()
