import unittest

from silicon.cache import Cache


class TestCache(unittest.TestCase):
    def test_direct_mapped_hand_worked_sequence(self):
        # 64B cache, 16B blocks -> 4 sets, direct-mapped (assoc=1).
        # addr 0/16/32/48 land in 4 distinct sets; addr 64 aliases addr 0's
        # set (same index, different tag) and evicts it.
        c = Cache("test", 64, 16, 1)
        seq = [0, 16, 32, 48, 0, 64, 0]
        results = [c.access(a) for a in seq]
        self.assertEqual(results, [False, False, False, False, True, False, False])
        self.assertEqual(c.stats.hits, 1)
        self.assertEqual(c.stats.misses, 6)

    def test_same_block_different_offset_is_one_line(self):
        c = Cache("test", 64, 16, 1)
        self.assertFalse(c.access(0))   # miss, loads the 0..15 block
        self.assertTrue(c.access(4))    # same block -> hit
        self.assertTrue(c.access(15))   # still same block -> hit
        self.assertFalse(c.access(16))  # next block -> miss

    def test_lru_eviction_order_2_way(self):
        c = Cache("test", 32, 16, 2)  # 1 set, 2-way
        self.assertFalse(c.access(0))    # miss; set = [0]
        self.assertFalse(c.access(16))   # miss; set = [0, 16]
        self.assertTrue(c.access(0))     # hit; set becomes [16, 0] (0 is now MRU)
        self.assertFalse(c.access(32))   # miss; evicts LRU (16); set = [0, 32]
        self.assertTrue(c.access(0))     # 0 should still be resident
        self.assertFalse(c.access(16))   # 16 was evicted -> miss

    def test_stats_hit_rate(self):
        c = Cache("test", 64, 16, 1)
        c.access(0)
        c.access(0)
        c.access(0)
        self.assertAlmostEqual(c.stats.hit_rate, 2 / 3)

    def test_bad_config_raises(self):
        with self.assertRaises(ValueError):
            Cache("test", 100, 16, 2)  # 100/16 isn't even an integer number of blocks
        with self.assertRaises(ValueError):
            Cache("test", 48, 16, 4)  # 3 blocks not divisible by associativity 4
        with self.assertRaises(ValueError):
            Cache("test", 64, 15, 1)  # block size not a power of two


if __name__ == "__main__":
    unittest.main()
