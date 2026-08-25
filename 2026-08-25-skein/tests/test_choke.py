import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein.choke import ChokeManager


class TestChokeManager(unittest.TestCase):
    def test_uninterested_peers_never_unchoked(self):
        cm = ChokeManager(is_seed=False)
        cm.record_download("a", 1000)
        cm.set_interested("a", False)
        result = cm.decide_unchoked(["a"])
        self.assertEqual(result, set())

    def test_top_k_by_download_rate_unchoked_when_leeching(self):
        cm = ChokeManager(is_seed=False, max_unchoked=2, optimistic_slots=0)
        for name, rate in [("a", 100), ("b", 500), ("c", 10), ("d", 300)]:
            cm.record_download(name, rate)
            cm.set_interested(name, True)
        result = cm.decide_unchoked(["a", "b", "c", "d"])
        self.assertEqual(result, {"b", "d"})  # highest two rates

    def test_seed_ranks_by_upload_rate_it_gives(self):
        cm = ChokeManager(is_seed=True, max_unchoked=1, optimistic_slots=0)
        cm.record_upload("a", 50)
        cm.record_upload("b", 900)
        cm.set_interested("a", True)
        cm.set_interested("b", True)
        result = cm.decide_unchoked(["a", "b"])
        self.assertEqual(result, {"b"})

    def test_optimistic_slot_picks_from_non_top_peers(self):
        rng = random.Random(42)
        cm = ChokeManager(is_seed=False, rng=rng, max_unchoked=1, optimistic_slots=1)
        for name, rate in [("a", 1000), ("b", 1), ("c", 1)]:
            cm.record_download(name, rate)
            cm.set_interested(name, True)
        result = cm.decide_unchoked(["a", "b", "c"])
        self.assertIn("a", result)  # the top-rate peer always gets its slot
        self.assertEqual(len(result), 2)  # 1 regular + 1 optimistic
        optimistic = result - {"a"}
        self.assertEqual(len(optimistic), 1)
        self.assertTrue(optimistic <= {"b", "c"})

    def test_fewer_interested_peers_than_slots(self):
        cm = ChokeManager(is_seed=False, max_unchoked=4, optimistic_slots=1)
        cm.record_download("a", 10)
        cm.set_interested("a", True)
        result = cm.decide_unchoked(["a"])
        self.assertEqual(result, {"a"})

    def test_no_interested_peers_returns_empty(self):
        cm = ChokeManager(is_seed=False)
        self.assertEqual(cm.decide_unchoked(["a", "b"]), set())

    def test_forget_clears_stats(self):
        cm = ChokeManager(is_seed=False)
        cm.record_download("a", 1000)
        cm.set_interested("a", True)
        cm.forget("a")
        # After forgetting, "a" is a brand-new peer with zero rate and
        # not interested, so it should not be unchoked even if re-added
        # to the connected set without re-declaring interest.
        result = cm.decide_unchoked(["a"])
        self.assertEqual(result, set())


if __name__ == "__main__":
    unittest.main()
