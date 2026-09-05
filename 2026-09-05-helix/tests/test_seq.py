import random
import unittest

from helix.seq import (
    SequenceError, parse_fasta, write_fasta, FastaRecord,
    parse_fastq, write_fastq, FastqRecord,
    reverse_complement, gc_content, transcribe, translate,
    validate_dna, random_genome, simulate_reads,
)


class TestBasics(unittest.TestCase):
    def test_reverse_complement(self):
        self.assertEqual(reverse_complement("ACGT"), "ACGT")
        self.assertEqual(reverse_complement("AACCGGTT"), "AACCGGTT")
        self.assertEqual(reverse_complement("ATCG"), "CGAT")
        self.assertEqual(reverse_complement(""), "")

    def test_reverse_complement_involution(self):
        rng = random.Random(0)
        for _ in range(50):
            s = "".join(rng.choice("ACGT") for _ in range(rng.randint(1, 100)))
            self.assertEqual(reverse_complement(reverse_complement(s)), s)

    def test_gc_content(self):
        self.assertAlmostEqual(gc_content("GGCC"), 1.0)
        self.assertAlmostEqual(gc_content("AATT"), 0.0)
        self.assertAlmostEqual(gc_content("ACGT"), 0.5)
        self.assertEqual(gc_content(""), 0.0)

    def test_transcribe(self):
        self.assertEqual(transcribe("ATGC"), "AUGC")

    def test_translate_to_stop(self):
        # ATG=M CCC=P TAA=stop
        self.assertEqual(translate("ATGCCCTAAGGG"), "MP")

    def test_translate_no_stop_flag(self):
        self.assertEqual(translate("ATGTAAGGG", to_stop=False), "M*G")

    def test_validate_dna_rejects_garbage(self):
        with self.assertRaises(SequenceError):
            validate_dna("ACGX")
        with self.assertRaises(SequenceError):
            validate_dna("")

    def test_validate_dna_uppercases(self):
        self.assertEqual(validate_dna("acgtN"), "ACGTN")


class TestFasta(unittest.TestCase):
    def test_round_trip(self):
        text = ">seq1 desc\nACGTACGT\nACGT\n>seq2\nTTTT\n"
        records = parse_fasta(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].header, "seq1 desc")
        self.assertEqual(records[0].sequence, "ACGTACGTACGT")
        self.assertEqual(records[1].sequence, "TTTT")
        out = write_fasta(records, width=1000)
        reparsed = parse_fasta(out)
        self.assertEqual([r.sequence for r in reparsed], [r.sequence for r in records])

    def test_wrap_width(self):
        rec = [FastaRecord("x", "A" * 25)]
        out = write_fasta(rec, width=10)
        lines = out.strip().splitlines()
        self.assertEqual(lines[1:], ["A" * 10, "A" * 10, "A" * 5])

    def test_empty_input_rejected(self):
        with self.assertRaises(SequenceError):
            parse_fasta("")
        with self.assertRaises(SequenceError):
            parse_fasta("not a fasta file at all")

    def test_sequence_before_header_rejected(self):
        with self.assertRaises(SequenceError):
            parse_fasta("ACGT\n>seq1\nACGT\n")


class TestFastq(unittest.TestCase):
    def test_round_trip(self):
        text = "@read1\nACGT\n+\nIIII\n@read2\nTTTT\n+read2\nJJJJ\n"
        records = parse_fastq(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].sequence, "ACGT")
        self.assertEqual(records[0].quality, "IIII")
        out = write_fastq(records)
        reparsed = parse_fastq(out)
        self.assertEqual(reparsed, records)

    def test_length_mismatch_rejected(self):
        with self.assertRaises(SequenceError):
            parse_fastq("@r\nACGT\n+\nII\n")

    def test_bad_record_count_rejected(self):
        with self.assertRaises(SequenceError):
            parse_fastq("@r\nACGT\n+\n")


class TestSimulation(unittest.TestCase):
    def test_random_genome_deterministic(self):
        g1 = random_genome(500, seed=7)
        g2 = random_genome(500, seed=7)
        self.assertEqual(g1, g2)
        self.assertEqual(len(g1), 500)
        g3 = random_genome(500, seed=8)
        self.assertNotEqual(g1, g3)

    def test_random_genome_rejects_bad_length(self):
        with self.assertRaises(SequenceError):
            random_genome(0, seed=1)
        with self.assertRaises(SequenceError):
            random_genome(-5, seed=1)

    def test_simulate_reads_deterministic(self):
        genome = random_genome(300, seed=1)
        r1 = simulate_reads(genome, n_reads=20, read_length=50, seed=2)
        r2 = simulate_reads(genome, n_reads=20, read_length=50, seed=2)
        self.assertEqual([r.sequence for r in r1], [r.sequence for r in r2])

    def test_simulate_reads_error_free_are_exact_substrings(self):
        genome = random_genome(300, seed=1)
        reads = simulate_reads(genome, n_reads=30, read_length=40, error_rate=0.0, seed=3, both_strands=True)
        for r in reads:
            if r.strand == "+":
                self.assertEqual(genome[r.true_start:r.true_end], r.sequence)
            else:
                self.assertEqual(reverse_complement(genome[r.true_start:r.true_end]), r.sequence)
            self.assertEqual(r.n_errors, 0)

    def test_simulate_reads_error_rate_produces_errors_at_scale(self):
        genome = random_genome(2000, seed=1)
        reads = simulate_reads(genome, n_reads=200, read_length=100, error_rate=0.05, seed=4, both_strands=False)
        total_errors = sum(r.n_errors for r in reads)
        total_bases = sum(len(r.sequence) for r in reads)
        # 5% error rate over 20,000 bases should produce roughly 1000 errors;
        # a wide tolerance band avoids test flakiness while still catching a
        # badly broken error model (e.g. one that injects zero errors).
        self.assertGreater(total_errors, 500)
        self.assertLess(total_errors, 1500)
        self.assertEqual(total_bases, 200 * 100)

    def test_simulate_reads_rejects_bad_params(self):
        genome = random_genome(100, seed=1)
        with self.assertRaises(SequenceError):
            simulate_reads(genome, n_reads=0, read_length=10, seed=1)
        with self.assertRaises(SequenceError):
            simulate_reads(genome, n_reads=5, read_length=200, seed=1)
        with self.assertRaises(SequenceError):
            simulate_reads(genome, n_reads=5, read_length=10, error_rate=1.0, seed=1)


if __name__ == "__main__":
    unittest.main()
