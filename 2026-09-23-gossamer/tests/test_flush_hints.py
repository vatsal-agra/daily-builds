"""Regression test for REVIEW.md #1: a hint-flush failure on the SECOND key
must not silently drop every key that hadn't been attempted yet."""
import unittest

from gossamer.node import NodeServer
from gossamer.vclock import VectorClock


class FailAfterN:
    """A stand-in for httpjson.post_json that fails starting from call N."""

    def __init__(self, fail_from_call):
        self.fail_from_call = fail_from_call
        self.calls = 0
        self.applied = []

    def __call__(self, host, port, path, payload, timeout=None):
        self.calls += 1
        if self.calls >= self.fail_from_call:
            from gossamer import httpjson
            raise httpjson.NodeUnreachable("simulated failure")
        self.applied.append(payload["key"])
        return 200, {"accepted": True}


class TestFlushHintsPartialFailure(unittest.TestCase):
    def setUp(self):
        peers = {"X": ("127.0.0.1", 1), "O": ("127.0.0.1", 2)}
        self.node = NodeServer("X", "127.0.0.1", 1, peers, n=1, r=1, w=1)
        for key in ["k1", "k2", "k3"]:
            self.node._apply_put(key, f"v-{key}", VectorClock().increment("X"), hint_for="O")

    def test_failure_on_second_key_keeps_all_unflushed_keys_recoverable(self):
        import gossamer.node as node_mod
        fake = FailAfterN(fail_from_call=2)  # k1 succeeds, k2 fails, k3 never attempted
        original = node_mod.httpjson.post_json
        node_mod.httpjson.post_json = fake
        try:
            self.node._flush_hints_for("O")
        finally:
            node_mod.httpjson.post_json = original

        self.assertEqual(fake.applied, ["k1"], "k1 should have been sent before the failure")

        # k1 succeeded and must be gone from the hint store.
        remaining = self.node.hints.get("O", {})
        self.assertNotIn("k1", remaining)

        # k2 (the one that failed) AND k3 (never attempted) must BOTH still
        # be recoverable -- this is the exact bug: k3 used to be lost.
        self.assertIn("k2", remaining, "k2 must be put back after its failed flush")
        self.assertIn("k3", remaining, "k3 must not be silently dropped")

    def test_successful_flush_of_all_keys_clears_the_hint_bucket(self):
        import gossamer.node as node_mod
        fake = FailAfterN(fail_from_call=999)  # never fails
        original = node_mod.httpjson.post_json
        node_mod.httpjson.post_json = fake
        try:
            self.node._flush_hints_for("O")
        finally:
            node_mod.httpjson.post_json = original

        self.assertEqual(sorted(fake.applied), ["k1", "k2", "k3"])
        self.assertEqual(self.node.hints.get("O", {}), {})


if __name__ == "__main__":
    unittest.main()
