import unittest

from sector.fat import Fat, FatFullError, FREE, EOC


class TestFatBasics(unittest.TestCase):
    def test_new_reserves_cluster_0_and_1(self):
        fat = Fat.new(count_of_clusters=10, media=0xF8)
        self.assertEqual(fat.entries[0], 0xFF00 | 0xF8)
        self.assertEqual(fat.entries[1], 0xFFFF)
        self.assertEqual(len(fat), 10)
        self.assertEqual(fat.count_free(), 10)

    def test_to_bytes_pads_to_region_size(self):
        fat = Fat.new(10, 0xF8)
        raw = fat.to_bytes(512)
        self.assertEqual(len(raw), 512)
        # only 12 real entries (10 data + 2 reserved) worth of bytes are meaningful
        self.assertTrue(all(b == 0 for b in raw[24:]))

    def test_from_bytes_trims_sector_padding(self):
        # regression for the Phase-3 bug: a FAT region sized in whole sectors
        # pads past the last real cluster with zero bytes that must NOT be
        # treated as additional free clusters.
        fat = Fat.new(10, 0xF8)
        raw = fat.to_bytes(512)  # 256 entries worth of bytes, only 12 are real
        reopened = Fat.from_bytes(raw, count_of_clusters=10)
        self.assertEqual(len(reopened.entries), 12)
        self.assertEqual(reopened.count_free(), 10)

    def test_from_bytes_rejects_undersized_region(self):
        with self.assertRaises(ValueError):
            Fat.from_bytes(b"\x00" * 4, count_of_clusters=100)


class TestChain(unittest.TestCase):
    def test_allocate_links_chain_and_terminates(self):
        fat = Fat.new(10, 0xF8)
        chain = fat.allocate(3)
        self.assertEqual(len(chain), 3)
        self.assertEqual(fat.entries[chain[0]], chain[1])
        self.assertEqual(fat.entries[chain[1]], chain[2])
        self.assertTrue(fat.is_eoc(fat.entries[chain[2]]))
        self.assertEqual(fat.chain(chain[0]), chain)

    def test_allocate_single_cluster(self):
        fat = Fat.new(10, 0xF8)
        chain = fat.allocate(1)
        self.assertEqual(len(chain), 1)
        self.assertTrue(fat.is_eoc(fat.entries[chain[0]]))

    def test_allocate_exhausts_and_raises(self):
        fat = Fat.new(3, 0xF8)
        fat.allocate(3)
        with self.assertRaises(FatFullError):
            fat.allocate(1)

    def test_allocate_zero_or_negative_rejected(self):
        fat = Fat.new(3, 0xF8)
        with self.assertRaises(ValueError):
            fat.allocate(0)
        with self.assertRaises(ValueError):
            fat.allocate(-1)

    def test_partial_allocation_never_committed_on_failure(self):
        fat = Fat.new(5, 0xF8)
        with self.assertRaises(FatFullError):
            fat.allocate(6)
        self.assertEqual(fat.count_free(), 5, "a failed allocate() must not consume any clusters")

    def test_extend_grows_existing_chain(self):
        fat = Fat.new(10, 0xF8)
        chain = fat.allocate(2)
        more = fat.extend(chain[0], 2)
        self.assertEqual(len(more), 2)
        full = fat.chain(chain[0])
        self.assertEqual(full, chain + more)

    def test_free_chain_marks_all_clusters_free(self):
        fat = Fat.new(10, 0xF8)
        chain = fat.allocate(4)
        fat.free_chain(chain[0])
        self.assertEqual(fat.count_free(), 10)
        for c in chain:
            self.assertTrue(fat.is_free(c))

    def test_free_chain_on_zero_is_a_noop(self):
        fat = Fat.new(10, 0xF8)
        fat.free_chain(0)  # should not raise
        self.assertEqual(fat.count_free(), 10)

    def test_chain_of_zero_is_empty(self):
        fat = Fat.new(10, 0xF8)
        self.assertEqual(fat.chain(0), [])

    def test_cyclic_chain_detected(self):
        fat = Fat.new(10, 0xF8)
        fat.entries[2] = 3
        fat.entries[3] = 2  # cycle
        with self.assertRaises(ValueError):
            fat.chain(2)

    def test_chain_into_free_cluster_detected(self):
        fat = Fat.new(10, 0xF8)
        fat.entries[2] = 0  # points at a free cluster instead of EOC
        with self.assertRaises(ValueError):
            fat.chain(2)

    def test_reused_clusters_after_free_are_lowest_first(self):
        fat = Fat.new(10, 0xF8)
        chain1 = fat.allocate(5)
        fat.free_chain(chain1[0])
        chain2 = fat.allocate(5)
        self.assertEqual(sorted(chain1), sorted(chain2))


if __name__ == "__main__":
    unittest.main()
