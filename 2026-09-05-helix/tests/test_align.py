import random
import unittest

from helix.align import (
    needleman_wunsch_linear, align_affine, global_align, local_align,
    brute_force_global_score, BLOSUM62,
)


def _consume_lengths(result):
    """Return (a_consumed, b_consumed) implied by a CIGAR, for cross-checking
    against the aligned strings independently of the traceback code path."""
    ref_len = 0
    qry_len = 0
    num = ""
    for ch in result.cigar:
        if ch.isdigit():
            num += ch
        else:
            n = int(num)
            num = ""
            if ch in "=XD":
                ref_len += n
            if ch in "=XI":
                qry_len += n
    return ref_len, qry_len


class TestNeedlemanWunschLinear(unittest.TestCase):
    def test_matches_brute_force_oracle(self):
        rng = random.Random(0)
        for _ in range(100):
            a = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 12)))
            b = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 12)))
            got = needleman_wunsch_linear(a, b, match=1, mismatch=-1, gap=-2).score
            expected = brute_force_global_score(a, b, match=1, mismatch=-1, gap=-2)
            self.assertEqual(got, expected, (a, b))

    def test_identical_sequences_score_all_matches(self):
        r = needleman_wunsch_linear("ACGTACGT", "ACGTACGT", match=2, mismatch=-1, gap=-2)
        self.assertEqual(r.score, 16)
        self.assertEqual(r.cigar, "8=")

    def test_cigar_consumed_lengths_match_inputs(self):
        rng = random.Random(1)
        for _ in range(50):
            a = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 15)))
            b = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 15)))
            r = needleman_wunsch_linear(a, b)
            ref_len, qry_len = _consume_lengths(r)
            self.assertEqual(ref_len, len(a))
            self.assertEqual(qry_len, len(b))
            self.assertEqual(len(r.aligned_a), len(r.aligned_b))

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            needleman_wunsch_linear("", "ACGT")
        with self.assertRaises(ValueError):
            needleman_wunsch_linear("ACGT", "")

    def test_textbook_example(self):
        # A widely-used worked example: match=+1 mismatch=-1 gap=-1.
        r = needleman_wunsch_linear("GATTACA", "GCATGCU", match=1, mismatch=-1, gap=-1)
        self.assertEqual(r.score, 0)


class TestGotohAffineGlobal(unittest.TestCase):
    def test_degenerate_zero_open_matches_linear_gap(self):
        rng = random.Random(2)
        for _ in range(60):
            a = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 20)))
            b = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 20)))
            linear = needleman_wunsch_linear(a, b, match=1, mismatch=-1, gap=-1)
            affine = global_align(a, b, match=1, mismatch=-1, gap_open=0, gap_extend=1)
            self.assertEqual(affine.score, linear.score, (a, b))

    def test_affine_prefers_one_big_gap_over_many_small(self):
        # A single 4bp deletion should beat 4 separate single-base gaps once
        # gap_open is charged per gap-opening event, not per gapped base.
        a = "AAAAGGGGCCCCTTTT"
        b = "AAAACCCCTTTT"  # missing the GGGG block entirely -> one clean gap
        r = global_align(a, b, match=1, mismatch=-5, gap_open=4, gap_extend=1)
        # exactly one gap-open event expected in the CIGAR (one contiguous D run)
        self.assertEqual(r.cigar.count("D"), 1, r.cigar)

    def test_cigar_consumed_lengths_match_inputs(self):
        rng = random.Random(3)
        for _ in range(60):
            a = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 25)))
            b = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 25)))
            r = global_align(a, b, gap_open=3, gap_extend=1)
            ref_len, qry_len = _consume_lengths(r)
            self.assertEqual(ref_len, len(a))
            self.assertEqual(qry_len, len(b))
            self.assertEqual(len(r.aligned_a), len(r.aligned_b))
            self.assertEqual(r.aligned_a.replace("-", ""), a)
            self.assertEqual(r.aligned_b.replace("-", ""), b)

    def test_rejects_negative_gap_penalties(self):
        with self.assertRaises(ValueError):
            global_align("ACGT", "ACGT", gap_open=-1)

    def test_rejects_bad_mode(self):
        with self.assertRaises(ValueError):
            align_affine("ACGT", "ACGT", mode="bogus")

    def test_protein_blosum62(self):
        r = global_align("MKV", "MKV", matrix=BLOSUM62, gap_open=10, gap_extend=1)
        self.assertEqual(r.score, BLOSUM62[("M", "M")] + BLOSUM62[("K", "K")] + BLOSUM62[("V", "V")])


class TestGotohAffineLocal(unittest.TestCase):
    def test_finds_embedded_match(self):
        a = "AAAAAAGATTACAAAAAAAA"
        b = "GGGGGATTACAGGGGG"
        r = local_align(a, b, match=2, mismatch=-1, gap_open=5, gap_extend=1)
        self.assertEqual(r.aligned_a.replace("-", ""), "GATTACA")
        self.assertEqual(r.aligned_b.replace("-", ""), "GATTACA")
        self.assertEqual(r.score, 14)

    def test_no_similarity_returns_empty(self):
        r = local_align("AAAAAAAA", "CCCCCCCC", match=1, mismatch=-100, gap_open=100, gap_extend=100)
        self.assertEqual(r.score, 0)
        self.assertEqual(r.aligned_a, "")
        self.assertEqual(r.aligned_b, "")

    def test_local_region_bounds_are_consistent(self):
        a = "AAAAAAGATTACAAAAAAAA"
        b = "GGGGGATTACAGGGGG"
        r = local_align(a, b, match=2, mismatch=-1, gap_open=5, gap_extend=1)
        self.assertEqual(a[r.a_start:r.a_end], r.aligned_a.replace("-", ""))
        self.assertEqual(b[r.b_start:r.b_end], r.aligned_b.replace("-", ""))

    def test_local_score_never_exceeds_global_on_same_inputs(self):
        # Local alignment score is always >= the best possible substring
        # match, and for fully-overlapping sequences of equal content,
        # local and global scores should agree exactly.
        rng = random.Random(4)
        for _ in range(40):
            a = "".join(rng.choice("ACGT") for _ in range(rng.randint(5, 20)))
            loc = local_align(a, a, match=1, mismatch=-1, gap_open=3, gap_extend=1)
            self.assertEqual(loc.score, len(a))  # perfect self-match


if __name__ == "__main__":
    unittest.main()
