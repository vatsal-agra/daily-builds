import random
import unittest

from helix.seq import random_genome, simulate_reads
from helix.fmindex import FMIndex
from helix.variants import (
    VariantError, PileupColumn, apply_variants, place_reads,
    build_pileup, call_variants, call_variants_from_reads,
)


class TestApplyVariants(unittest.TestCase):
    def test_single_substitution(self):
        ref = "ACGTACGT"
        mutated = apply_variants(ref, [(2, "T")])
        self.assertEqual(mutated, "ACTTACGT")
        self.assertEqual(len(mutated), len(ref))

    def test_multiple_edits(self):
        ref = "AAAAAAAA"
        mutated = apply_variants(ref, [(0, "T"), (7, "G")])
        self.assertEqual(mutated, "TAAAAAAG")

    def test_rejects_out_of_range(self):
        with self.assertRaises(VariantError):
            apply_variants("ACGT", [(10, "A")])
        with self.assertRaises(VariantError):
            apply_variants("ACGT", [(-1, "A")])


class TestPlaceReads(unittest.TestCase):
    def test_places_exact_reads(self):
        ref = random_genome(1000, seed=1)
        idx = FMIndex(ref)
        reads = [ref[100:150], ref[500:560]]
        placed, summary = place_reads(idx, reads, seed_length=20)
        self.assertEqual(summary.n_placed, 2)
        self.assertEqual(summary.n_unplaced, 0)
        positions = sorted(p for p, _ in placed)
        self.assertEqual(positions, [100, 500])

    def test_placement_tolerates_scattered_mismatches(self):
        ref = random_genome(1000, seed=2)
        idx = FMIndex(ref)
        rng = random.Random(3)
        read = list(ref[200:300])
        read[10] = rng.choice([b for b in "ACGT" if b != read[10]])
        read[80] = rng.choice([b for b in "ACGT" if b != read[80]])
        placed, summary = place_reads(idx, ["".join(read)], seed_length=20)
        self.assertEqual(summary.n_placed, 1)
        self.assertEqual(placed[0][0], 200)

    def test_unplaceable_read_reported(self):
        ref = random_genome(500, seed=4)
        idx = FMIndex(ref)
        placed, summary = place_reads(idx, ["N" * 40], seed_length=20)
        self.assertEqual(summary.n_placed, 0)
        self.assertEqual(summary.n_unplaced, 1)

    def test_rejects_bad_seed_length(self):
        idx = FMIndex(random_genome(100, seed=1))
        with self.assertRaises(VariantError):
            place_reads(idx, ["ACGT"], seed_length=0)


class TestPileupAndCalling(unittest.TestCase):
    def test_build_pileup_basic_counts(self):
        ref = "ACGTACGT"
        reads = [(0, "ACGT"), (0, "ACGT"), (4, "ACGT")]
        pileup = build_pileup(ref, reads)
        self.assertEqual(len(pileup), len(ref))
        self.assertEqual(pileup[0].base_counts["A"], 2)
        self.assertEqual(pileup[0].depth, 2)
        self.assertEqual(pileup[4].base_counts["A"], 1)

    def test_pileup_ignores_out_of_bounds_positions(self):
        ref = "ACGT"
        reads = [(2, "GTAA")]  # extends 2 bases past the end of ref
        pileup = build_pileup(ref, reads)
        self.assertEqual(pileup[2].depth, 1)
        self.assertEqual(pileup[3].depth, 1)  # positions 4,5 silently dropped

    def test_rejects_empty_reference(self):
        with self.assertRaises(VariantError):
            build_pileup("", [(0, "ACGT")])

    def test_call_variants_majority_snp(self):
        ref = "AAAA"
        # position 1: 5 reads say 'T', 1 says 'A' (ref) -> AF=5/6 > 0.5
        reads = [(0, "ATAA")] * 5 + [(0, "AAAA")]
        pileup = build_pileup(ref, reads)
        variants = call_variants(pileup, min_depth=4, min_allele_frequency=0.5)
        self.assertEqual(len(variants), 1)
        v = variants[0]
        self.assertEqual(v.position, 1)
        self.assertEqual(v.ref_base, "A")
        self.assertEqual(v.alt_base, "T")
        self.assertEqual(v.alt_count, 5)
        self.assertAlmostEqual(v.allele_frequency, 5 / 6)

    def test_call_variants_respects_min_depth(self):
        ref = "AAAA"
        reads = [(0, "TAAA")] * 2  # only depth 2 at position 0
        pileup = build_pileup(ref, reads)
        self.assertEqual(call_variants(pileup, min_depth=4), [])
        self.assertEqual(len(call_variants(pileup, min_depth=2)), 1)

    def test_call_variants_no_false_positive_on_matching_reference(self):
        ref = "ACGTACGT"
        reads = [(0, "ACGTACGT")] * 10
        pileup = build_pileup(ref, reads)
        self.assertEqual(call_variants(pileup, min_depth=4), [])

    def test_rejects_bad_thresholds(self):
        pileup = [PileupColumn(0, "A", {"A": 5}, 5)]
        with self.assertRaises(VariantError):
            call_variants(pileup, min_depth=0)
        with self.assertRaises(VariantError):
            call_variants(pileup, min_allele_frequency=0)
        with self.assertRaises(VariantError):
            call_variants(pileup, min_allele_frequency=1.5)


class TestEndToEndVariantCalling(unittest.TestCase):
    def test_recovers_injected_snps_with_no_false_positives(self):
        ref = random_genome(3000, seed=99)
        rng = random.Random(1)
        snp_positions = sorted(rng.sample(range(100, 2900), 5))
        edits = [(p, rng.choice([b for b in "ACGT" if b != ref[p]])) for p in snp_positions]
        sample = apply_variants(ref, edits)
        reads = simulate_reads(sample, n_reads=800, read_length=100, error_rate=0.01, seed=7, both_strands=False)
        idx = FMIndex(ref)
        variants, summary = call_variants_from_reads(ref, idx, [r.sequence for r in reads])
        called = {v.position for v in variants}
        true_positions = {p for p, _ in edits}
        self.assertEqual(called, true_positions)
        self.assertGreater(summary.n_placed, 0.9 * summary.n_reads)

    def test_no_snps_calls_nothing(self):
        ref = random_genome(1000, seed=5)
        reads = simulate_reads(ref, n_reads=300, read_length=80, error_rate=0.01, seed=6, both_strands=False)
        idx = FMIndex(ref)
        variants, summary = call_variants_from_reads(ref, idx, [r.sequence for r in reads])
        self.assertEqual(variants, [])


if __name__ == "__main__":
    unittest.main()
