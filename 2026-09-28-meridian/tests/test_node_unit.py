"""Unit tests of the Chord algorithms themselves, over an in-memory,
no-socket RPC transport (see helpers.build_in_memory_rpc) so they run fast
and deterministically, independent of any real network."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian.node import KeyNotFoundError, NodeRef, iterative_find_successor  # noqa: E402
from tests.helpers import build_in_memory_rpc, converge, make_node_at_id  # noqa: E402


class TestChordPaperWorkedExample(unittest.TestCase):
    """Reproduces the exact 3-bit, 3-node ring from the original Chord
    paper (Stoica, Morris, Karger, Kaashoek, Balakrishnan; SIGCOMM 2001),
    Figure 3/4/5: nodes at identifiers {0, 1, 3} on an 8-point ring, keys
    at {1, 2, 6} landing on successors {1, 3, 0} respectively. This is a
    published, independently-checkable ground truth, not a value the
    implementation invented for itself.
    """

    M_BITS = 3  # ring size 8, per the paper's example

    def setUp(self):
        self.registry = {}
        self.rpc_call = build_in_memory_rpc(self.registry)
        self.n0 = make_node_at_id(0, "h0", 10000, self.M_BITS, r=1)
        self.n1 = make_node_at_id(1, "h1", 10001, self.M_BITS, r=1)
        self.n3 = make_node_at_id(3, "h3", 10003, self.M_BITS, r=1)
        for n in (self.n0, self.n1, self.n3):
            n._rpc_pusher = self.rpc_call
            self.registry[n.ref.id] = n

        # Join in an order that is *not* sorted, to make sure convergence
        # doesn't depend on nodes arriving in ring order.
        self.n0.join(None, self.rpc_call)
        self.n3.join(self.n0.ref, self.rpc_call)
        self.n1.join(self.n0.ref, self.rpc_call)
        converge([self.n0, self.n1, self.n3], self.rpc_call)

    def test_successor_predecessor_pointers_match_the_paper(self):
        self.assertEqual(self.n0.successor_list[0].id, 1)
        self.assertEqual(self.n0.predecessor.id, 3)
        self.assertEqual(self.n1.successor_list[0].id, 3)
        self.assertEqual(self.n1.predecessor.id, 0)
        self.assertEqual(self.n3.successor_list[0].id, 0)
        self.assertEqual(self.n3.predecessor.id, 1)

    def test_finger_tables_match_the_paper_exactly(self):
        # Figure 3(b) of the paper, expressed as our 0-indexed finger[i]
        # (paper's finger[i+1]): node 0 -> [1, 3, 0]; node 1 -> [3, 3, 0];
        # node 3 -> [0, 0, 0].
        self.assertEqual([f.id for f in self.n0.finger], [1, 3, 0])
        self.assertEqual([f.id for f in self.n1.finger], [3, 3, 0])
        self.assertEqual([f.id for f in self.n3.finger], [0, 0, 0])

    def test_key_lookup_matches_the_paper(self):
        # successor(1) = 1, successor(2) = 3, successor(6) = 0
        for key_id, expected_node_id in ((1, 1), (2, 3), (6, 0)):
            for start in (self.n0, self.n1, self.n3):
                with self.subTest(key_id=key_id, start=start.ref.id):
                    result, hops = iterative_find_successor(start.ref, key_id, self.rpc_call)
                    self.assertEqual(result.id, expected_node_id)
                    # 3 nodes, m=3: no lookup should need more than 3 hops.
                    self.assertLessEqual(len(hops), 3)

    def test_put_and_get_round_trip_through_the_converged_ring(self):
        from meridian import node as node_mod

        node_mod.put("somekey", "someval", self.n0.ref, self.rpc_call, m_bits=self.M_BITS)
        value, hops = node_mod.get("somekey", self.n1.ref, self.rpc_call, m_bits=self.M_BITS)
        self.assertEqual(value, "someval")
        self.assertGreaterEqual(len(hops), 1)


class TestNotifyKeyMigration(unittest.TestCase):
    """A node accepting a new predecessor must hand over exactly the keys
    that now belong to it, and nothing else."""

    M_BITS = 8

    def setUp(self):
        self.registry = {}
        self.rpc_call = build_in_memory_rpc(self.registry)

    def test_migrates_only_keys_in_the_new_predecessors_range(self):
        from meridian import hashing

        def key_with_id_in(prefix, lo, hi):
            i = 0
            while True:
                k = f"{prefix}{i}"
                kid = hashing.key_id(k, self.M_BITS)
                if lo <= kid < hi:
                    return k, kid
                i += 1

        # Real keys, real hashing -- not fabricated ids -- so migration
        # exercises the exact code path `put()` uses (rehashing the key
        # string on the target after the move).
        k_low, id_low = key_with_id_in("low", 0, 50)        # wraps into B's new range too
        k_mid, id_mid = key_with_id_in("mid", 50, 150)      # moves to B
        k_high, id_high = key_with_id_in("high", 150, 250)  # stays with A

        a = make_node_at_id(250, "hA", 1, self.M_BITS, r=1)  # alone: owns the whole ring
        a._rpc_pusher = self.rpc_call
        self.registry[a.ref.id] = a
        for k in (k_low, k_mid, k_high):
            a.rpc_store(k, f"v-{k}")

        b = make_node_at_id(150, "hB", 2, self.M_BITS, r=1)
        b._rpc_pusher = self.rpc_call
        self.registry[b.ref.id] = b

        # B notifies A it might be A's predecessor. A's predecessor was
        # None (full-ring owner), so the range that hands over to B is
        # (A.id=250, B.id=150] wrapping around 0 -- i.e. every id <= 150
        # or > 250. id_mid (50<=id<150) falls in that wrap; id_low
        # (<50) also does; id_high (150<=id<250) does not.
        a.notify(b.ref)

        self.assertNotIn(id_mid, a.data)
        self.assertIn(id_mid, b.data)
        self.assertEqual(b.data[id_mid], (k_mid, f"v-{k_mid}"))
        self.assertIn(id_high, a.data)
        self.assertNotIn(id_high, b.data)
        # id_low is also < B's id (150) so it wraps into the migrated
        # range same as id_mid.
        self.assertIn(id_low, b.data)

    def test_does_not_accept_a_worse_predecessor_candidate(self):
        a = make_node_at_id(200, "hA", 1, self.M_BITS, r=1)
        a._rpc_pusher = self.rpc_call
        self.registry[a.ref.id] = a
        good = make_node_at_id(150, "hGood", 2, self.M_BITS, r=1)
        self.registry[good.ref.id] = good
        worse = make_node_at_id(140, "hWorse", 3, self.M_BITS, r=1)
        self.registry[worse.ref.id] = worse

        a.notify(good.ref)
        self.assertEqual(a.predecessor.id, 150)
        a.notify(worse.ref)  # 140 is further from A than 150 is -- reject
        self.assertEqual(a.predecessor.id, 150)


class TestFaultTolerantLookup(unittest.TestCase):
    """Exercises the dead-hop fallback path in iterative_find_successor
    directly (see REVIEW.md bug #2) without needing real processes."""

    M_BITS = 8

    def setUp(self):
        self.registry = {}
        self.rpc_call = build_in_memory_rpc(self.registry)
        ids = [10, 60, 110, 160, 210]
        self.nodes = [make_node_at_id(i, f"h{i}", i, self.M_BITS, r=3) for i in ids]
        for n in self.nodes:
            n._rpc_pusher = self.rpc_call
            self.registry[n.ref.id] = n
        first, rest = self.nodes[0], self.nodes[1:]
        first.join(None, self.rpc_call)
        for n in rest:
            n.join(first.ref, self.rpc_call)
        converge(self.nodes, self.rpc_call)

    def test_lookup_reroutes_around_a_dead_finger_table_entry(self):
        # This is a regression test for REVIEW.md bug #2: the fallback
        # branch inside iterative_find_successor's loop, taken when a node
        # it is actively trying to route *through* (as opposed to the
        # final answer some node merely *reports*) turns out to be dead.
        # Force it directly by corrupting a live node's own finger table
        # entry to point at an id that was never a real member.
        first = self.nodes[0]
        ghost = NodeRef(id=999, host="ghost", port=1)
        for i in range(first.m_bits):
            first.finger[i] = ghost

        # first.local_find_successor_step for an id far from `first` will
        # now try to route via the corrupted finger (`ghost`) instead of a
        # real node; the client-side fallback must notice `ghost` doesn't
        # exist, ask `first` (the last good hop) for its successor list,
        # and continue from a real candidate instead of raising.
        result, hops = iterative_find_successor(first.ref, 205, self.rpc_call)
        self.assertNotEqual(result.id, ghost.id)
        self.assertNotIn(ghost.id, [h.id for h in hops])
        self.assertIn(result.id, self.registry)


class TestGetPutSurviveAPrimaryOwnersDeath(unittest.TestCase):
    """Covers the exact gap closed in this phase: routing can legitimately
    report an already-dead node as "responsible" (iterative_find_successor
    never itself verifies liveness of the node it reports -- see its
    docstring), so get()/put() must recover via successor-list replicas
    themselves rather than letting the RPC failure propagate out raw."""

    M_BITS = 10

    def setUp(self):
        from meridian import node as node_mod

        self.node_mod = node_mod
        self.registry = {}
        self.rpc_call = build_in_memory_rpc(self.registry)
        ids = [50, 200, 350, 500, 650, 800, 950]
        self.nodes = [make_node_at_id(i, f"h{i}", i, self.M_BITS, r=3) for i in ids]
        for n in self.nodes:
            n._rpc_pusher = self.rpc_call
            self.registry[n.ref.id] = n
        first, rest = self.nodes[0], self.nodes[1:]
        first.join(None, self.rpc_call)
        for n in rest:
            n.join(first.ref, self.rpc_call)
        converge(self.nodes, self.rpc_call)

    def test_get_recovers_from_replica_after_primary_dies(self):
        entry = self.node_mod.put("k1", "v1", self.nodes[0].ref, self.rpc_call, m_bits=self.M_BITS)
        primary_ref = entry[0]

        del self.registry[primary_ref.id]
        # a still-live node used as the routing start point
        alive_start = next(n.ref for n in self.nodes if n.ref.id != primary_ref.id)

        value, hops = self.node_mod.get("k1", alive_start, self.rpc_call, m_bits=self.M_BITS)
        self.assertEqual(value, "v1")
        self.assertNotIn(primary_ref.id, [h.id for h in hops])

    def test_put_recovers_when_the_reported_owner_is_already_dead(self):
        # Find which node WOULD be reported responsible for "k2" before it
        # exists anywhere, then kill it, then put() the key anyway -- this
        # is exactly the case iterative_find_successor's docstring warns
        # about: routing can report a dead node with no verification.
        from meridian import hashing

        kid = hashing.key_id("k2", self.M_BITS)
        would_be_owner, _ = iterative_find_successor(self.nodes[0].ref, kid, self.rpc_call)
        del self.registry[would_be_owner.id]
        alive_start = next(n.ref for n in self.nodes if n.ref.id != would_be_owner.id)

        stored_on, hops = self.node_mod.put("k2", "v2", alive_start, self.rpc_call, m_bits=self.M_BITS)
        self.assertNotEqual(stored_on.id, would_be_owner.id)

        value, _ = self.node_mod.get("k2", alive_start, self.rpc_call, m_bits=self.M_BITS)
        self.assertEqual(value, "v2")


if __name__ == "__main__":
    unittest.main()
