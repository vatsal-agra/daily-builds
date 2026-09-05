import random
import unittest

from helix.seq import random_genome, simulate_reads
from helix.fmindex import (
    build_suffix_array, bwt_from_suffix_array, invert_bwt, FMIndex,
    FMIndexError, naive_search, align_reads, place_read_by_seeds, SENTINEL,
)


class TestSuffixArray(unittest.TestCase):
    def test_known_example(self):
        # classic textbook example
        sa = build_suffix_array("banana" + SENTINEL)
        self.assertEqual(sa, [6, 5, 3, 1, 0, 4, 2])

    def test_suffix_array_is_sorted_order(self):
        rng = random.Random(0)
        for _ in range(50):
            s = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 60))) + SENTINEL
            sa = build_suffix_array(s)
            suffixes = [s[i:] for i in sa]
            self.assertEqual(suffixes, sorted(suffixes))
            self.assertEqual(sorted(sa), list(range(len(s))))  # a permutation

    def test_empty_string(self):
        self.assertEqual(build_suffix_array(""), [])


class TestBWTRoundTrip(unittest.TestCase):
    def test_known_example(self):
        sa = build_suffix_array("banana" + SENTINEL)
        bwt = bwt_from_suffix_array("banana" + SENTINEL, sa)
        self.assertEqual(bwt, "annb$aa")

    def test_fuzz_round_trip(self):
        rng = random.Random(1)
        for _ in range(300):
            n = rng.randint(1, 100)
            s = "".join(rng.choice("ACGT") for _ in range(n))
            sa = build_suffix_array(s + SENTINEL)
            bwt = bwt_from_suffix_array(s + SENTINEL, sa)
            self.assertEqual(invert_bwt(bwt), s)

    def test_single_character(self):
        s = "A"
        sa = build_suffix_array(s + SENTINEL)
        bwt = bwt_from_suffix_array(s + SENTINEL, sa)
        self.assertEqual(invert_bwt(bwt), s)

    def test_all_same_character(self):
        s = "AAAAAAAA"
        sa = build_suffix_array(s + SENTINEL)
        bwt = bwt_from_suffix_array(s + SENTINEL, sa)
        self.assertEqual(invert_bwt(bwt), s)

    def test_rejects_empty_bwt(self):
        with self.assertRaises(FMIndexError):
            invert_bwt("")


class TestFMIndexSearch(unittest.TestCase):
    def test_fuzz_matches_naive_search(self):
        rng = random.Random(2)
        for _ in range(400):
            n = rng.randint(5, 250)
            ref = "".join(rng.choice("ACGT") for _ in range(n))
            interval = rng.choice([1, 2, 3, 5, 16, 32])
            idx = FMIndex(ref, checkpoint_interval=interval)
            m = rng.randint(1, min(15, n))
            pat = "".join(rng.choice("ACGT") for _ in range(m))
            got = sorted(idx.search(pat))
            expected = sorted(naive_search(ref, pat))
            self.assertEqual(got, expected, (ref, pat, interval))
            self.assertEqual(idx.count(pat), len(expected))

    def test_pattern_not_present(self):
        idx = FMIndex("ACGTACGTACGT")
        self.assertEqual(idx.search("TTTT"), [])
        self.assertEqual(idx.count("TTTT"), 0)

    def test_pattern_covers_whole_reference(self):
        idx = FMIndex("ACGTACGT")
        self.assertEqual(idx.search("ACGTACGT"), [0])

    def test_overlapping_occurrences_all_found(self):
        idx = FMIndex("AAAAA")
        self.assertEqual(sorted(idx.search("AA")), [0, 1, 2, 3])

    def test_rejects_empty_reference(self):
        with self.assertRaises(FMIndexError):
            FMIndex("")

    def test_rejects_sentinel_in_reference(self):
        with self.assertRaises(FMIndexError):
            FMIndex("ACG" + SENTINEL + "T")

    def test_rejects_empty_pattern(self):
        idx = FMIndex("ACGT")
        with self.assertRaises(FMIndexError):
            idx.search("")

    def test_checkpoint_interval_does_not_change_results(self):
        ref = random_genome(400, seed=3)
        patterns = ["ACGT", ref[50:70], ref[0:10], ref[-10:]]
        results = []
        for interval in (1, 4, 16, 64, 1000):
            idx = FMIndex(ref, checkpoint_interval=interval)
            results.append([sorted(idx.search(p)) for p in patterns])
        for r in results[1:]:
            self.assertEqual(r, results[0])


class TestReadAlignment(unittest.TestCase):
    def test_exact_reads_map_to_true_position_both_strands(self):
        genome = random_genome(3000, seed=11)
        idx = FMIndex(genome)
        reads = simulate_reads(genome, n_reads=150, read_length=60, error_rate=0.0, seed=5, both_strands=True)
        aligned = align_reads(idx, [(r.read_id, r.sequence) for r in reads])
        for a, r in zip(aligned, reads):
            self.assertTrue(a.mapped, (r.read_id, r.strand))
            self.assertIn(r.true_start, a.positions)

    def test_read_with_no_origin_in_reference_is_unmapped(self):
        idx = FMIndex(random_genome(500, seed=1))
        aligned = align_reads(idx, [("bogus", "N" * 30)])
        self.assertFalse(aligned[0].mapped)

    def test_seed_and_vote_placement_tolerates_scattered_mismatches(self):
        genome = random_genome(2000, seed=4)
        idx = FMIndex(genome)
        rng = random.Random(9)
        start = 500
        read = list(genome[start:start + 150])
        # introduce 2 scattered substitutions
        for pos in (30, 100):
            orig = read[pos]
            read[pos] = rng.choice([b for b in "ACGT" if b != orig])
        read = "".join(read)
        # a whole-read exact search must fail (this is exactly why
        # seed-and-vote placement exists)
        self.assertEqual(idx.search(read), [])
        placed = place_read_by_seeds(idx, read, seed_length=20)
        self.assertEqual(placed, start)


if __name__ == "__main__":
    unittest.main()
