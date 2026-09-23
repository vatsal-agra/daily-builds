"""Regression tests for REVIEW.md #3 (N/R/W validation) and #4 (malformed
context returns a clean 400 instead of a raw 500)."""
import unittest

from gossamer.node import NodeServer


class TestNRWValidation(unittest.TestCase):
    def _peers(self):
        return {"A": ("127.0.0.1", 1), "B": ("127.0.0.1", 2), "C": ("127.0.0.1", 3)}

    def test_w_greater_than_n_rejected(self):
        with self.assertRaises(ValueError):
            NodeServer("A", "127.0.0.1", 1, self._peers(), n=2, r=2, w=3)

    def test_r_greater_than_n_rejected(self):
        with self.assertRaises(ValueError):
            NodeServer("A", "127.0.0.1", 1, self._peers(), n=2, r=3, w=2)

    def test_n_zero_rejected(self):
        with self.assertRaises(ValueError):
            NodeServer("A", "127.0.0.1", 1, self._peers(), n=0, r=0, w=0)

    def test_valid_config_accepted(self):
        node = NodeServer("A", "127.0.0.1", 1, self._peers(), n=3, r=2, w=2)
        self.assertEqual((node.n, node.r, node.w), (3, 2, 2))


class TestContextValidation(unittest.TestCase):
    def _node(self):
        # Single-node "cluster" so the one replica for any key is always
        # this node itself (in-process put), keeping this a pure unit test
        # of validation logic with no real network involved.
        peers = {"A": ("127.0.0.1", 1)}
        return NodeServer("A", "127.0.0.1", 1, peers, n=1, r=1, w=1)

    def test_none_context_is_valid(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", None)
        self.assertEqual(status, 200)

    def test_list_of_dicts_is_valid(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", [{"A": 1}])
        self.assertEqual(status, 200)

    def test_dict_context_rejected_cleanly(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", {"A": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_string_context_rejected_cleanly(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", "not-a-context")
        self.assertEqual(status, 400)

    def test_context_with_non_dict_element_rejected_cleanly(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", ["not-a-dict"])
        self.assertEqual(status, 400)

    def test_context_with_non_int_counter_rejected_cleanly(self):
        node = self._node()
        body, status = node.coordinate_put("k", "v", [{"A": "not-an-int"}])
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
