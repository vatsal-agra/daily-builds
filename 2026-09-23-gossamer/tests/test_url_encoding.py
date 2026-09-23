"""Regression test for REVIEW.md #2: keys containing reserved URL
characters must round-trip correctly, including when a preferred replica is
genuinely remote from the coordinator (which is why this needs more nodes
than N -- with N == total nodes every internal call is in-process and the
bug never gets exercised)."""
import unittest

from gossamer import client
from gossamer.cluster import Cluster
from gossamer.hashring import HashRing

NODE_IDS = ["A", "B", "C", "D", "E"]
VNODES = 32

TRICKY_KEYS = [
    "a key with spaces",
    "a&b=c",
    "hash#fragment",
    "percent%20encoded",
    "plus+sign",
    "slash/inside/key",
    "unicode-éè-key",
]


class TestUrlEncoding(unittest.TestCase):
    def test_tricky_keys_roundtrip_through_every_coordinator(self):
        with Cluster(NODE_IDS, base_port=9760, n=3, r=2, w=2, vnodes=VNODES) as c:
            for key in TRICKY_KEYS:
                status, body = client.put(c, "A", key, f"value-for-{key}", context=None)
                self.assertEqual(status, 200, f"PUT failed for key={key!r}: {body}")

            ring = HashRing(vnodes=VNODES)
            for nid in NODE_IDS:
                ring.add_node(nid)

            for key in TRICKY_KEYS:
                for coordinator in NODE_IDS:  # exercise remote AND local paths
                    status, body = client.get(c, coordinator, key)
                    self.assertEqual(status, 200, f"GET failed for key={key!r} via {coordinator}: {body}")
                    self.assertEqual(
                        body["siblings"][0]["value"], f"value-for-{key}",
                        f"wrong value for key={key!r} via coordinator {coordinator}: {body}"
                    )

    def test_tricky_key_replicas_agree_directly_without_read_repair_masking_it(self):
        # Query each preferred replica DIRECTLY (not through the quorum
        # merge) to make sure the underlying internal RPC itself decoded
        # the key correctly, rather than relying on read-repair to paper
        # over a wrong answer from one replica.
        with Cluster(NODE_IDS, base_port=9770, n=3, r=2, w=2, vnodes=VNODES) as c:
            key = "a&b=c#tricky"
            status, _ = client.put(c, "A", key, "the-real-value", context=None)
            self.assertEqual(status, 200)

            ring = HashRing(vnodes=VNODES)
            for nid in NODE_IDS:
                ring.add_node(nid)
            owners = ring.replicas_for(key, 3)

            for owner in owners:
                status, body = client.get(c, owner, key)
                self.assertEqual(status, 200)
                self.assertEqual(body["siblings"][0]["value"], "the-real-value",
                                  f"replica {owner} disagrees for key={key!r}")


if __name__ == "__main__":
    unittest.main()
