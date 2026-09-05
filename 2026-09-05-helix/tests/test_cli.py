import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def run_cli(*args):
    result = subprocess.run(
        [sys.executable, "-m", "helix.cli", *args],
        capture_output=True, text=True, timeout=60,
    )
    return result


class TestCLI(unittest.TestCase):
    def test_demo_runs_clean(self):
        r = run_cli("demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Demo complete", r.stdout)
        self.assertIn("exact full reconstruction=True", r.stdout)

    def test_align_global(self):
        r = run_cli("align", "--a", "GATTACA", "--b", "GATCACA", "--mode", "global")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("score:", r.stdout)
        self.assertIn("cigar:", r.stdout)

    def test_align_local(self):
        r = run_cli("align", "--a", "AAAGATTACAAAA", "--b", "GGGGATTACAGGGG", "--mode", "local")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GATTACA", r.stdout)

    def test_align_rejects_empty(self):
        r = run_cli("align", "--a", "", "--b", "ACGT")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)

    def test_index_and_search(self):
        r = run_cli("index", "--genome-length", "300", "--seed", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BWT", r.stdout)

        r2 = run_cli("search", "--genome-length", "300", "--seed", "1", "--pattern", "ACGT")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("occurrences:", r2.stdout)

    def test_assemble(self):
        r = run_cli(
            "assemble", "--genome-length", "800", "--n-reads", "2000",
            "--read-length", "80", "--error-rate", "0.0", "--k", "21", "--seed", "3",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contigs:", r.stdout)

    def test_simulate(self):
        r = run_cli("simulate", "--genome-length", "200", "--n-reads", "10", "--seed", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("simulated 10 reads", r.stdout)

    def test_phylo_needs_fasta(self):
        r = run_cli("phylo")
        self.assertNotEqual(r.returncode, 0)

    def test_phylo_with_fasta_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta_path = Path(tmp) / "seqs.fasta"
            fasta_path.write_text(
                ">a\nACGTACGTTGCATGCACGTAGCTAGCATGCA\n"
                ">b\nACGTACGTTGCATCCACGTAGCTAGCATGCA\n"
                ">c\nACGTACCTTGCATGCACGTAGATAGCATGCA\n"
            )
            r = run_cli("phylo", "--fasta", str(fasta_path), "--method", "nj")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(";", r.stdout)  # Newick output
            self.assertIn("a", r.stdout)
            self.assertIn("b", r.stdout)
            self.assertIn("c", r.stdout)

    def test_no_subcommand_shows_usage_error(self):
        r = run_cli()
        self.assertNotEqual(r.returncode, 0)

    def test_search_rejects_bad_pattern_gracefully(self):
        r = run_cli("search", "--genome-length", "100", "--seed", "1", "--pattern", "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)

    def test_index_rejects_bad_checkpoint_interval(self):
        # REVIEW.md #1
        r = run_cli("index", "--genome-length", "100", "--seed", "1", "--checkpoint-interval", "0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_assemble_rejects_read_length_shorter_than_k(self):
        # REVIEW.md #2
        r = run_cli("assemble", "--genome-length", "200", "--read-length", "10", "--k", "21", "--seed", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)

    def test_multi_record_fasta_warns_instead_of_silently_dropping(self):
        # REVIEW.md #4
        with tempfile.TemporaryDirectory() as tmp:
            fasta_path = Path(tmp) / "multi.fasta"
            fasta_path.write_text(">first\nACGTACGTACGTACGTACGTACGTACGT\n>second\nTTTTTTTTTTTTTTTTTTTTTTTTTTTT\n")
            r = run_cli("search", "--fasta", str(fasta_path), "--pattern", "TTTTTT")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("warning", r.stderr)
            self.assertIn("first", r.stderr)

    def test_duplicate_fasta_header_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta_path = Path(tmp) / "dup.fasta"
            fasta_path.write_text(">a\nACGT\n>a\nTTTT\n>b\nGGGG\n")
            r = run_cli("phylo", "--fasta", str(fasta_path))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("duplicate", r.stderr)

    def test_callvariants_recovers_snps(self):
        r = run_cli("callvariants", "--genome-length", "3000", "--n-snps", "5",
                    "--n-reads", "800", "--seed", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("true positives:  5/5", r.stdout)
        self.assertIn("false positives: []", r.stdout)

    def test_callvariants_rejects_too_many_snps(self):
        r = run_cli("callvariants", "--genome-length", "100", "--n-snps", "500", "--seed", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)

    def test_bad_output_path_reported_cleanly(self):
        # REVIEW.md #6
        r = run_cli("simulate", "--genome-length", "100", "--seed", "1",
                     "--out-fasta", "/nonexistent_dir_xyz/out.fasta")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_viz_writes_self_contained_html_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "report.html"
            r = run_cli("viz", "--out", str(out_path), "--genome-length", "300", "--seed", "1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertTrue(content.startswith("<!doctype html>"))
            for tab in ("Alignment", "Phylogenetics", "Assembly", "Variant Calling"):
                self.assertIn(tab, content)
            self.assertIn("<svg", content)

    def test_viz_bad_output_path_reported_cleanly(self):
        r = run_cli("viz", "--out", "/nonexistent_dir_xyz/report.html", "--genome-length", "200", "--seed", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_viz_rejects_too_small_genome_length(self):
        # found during Phase 4 polish: a small --genome-length used to
        # crash with a raw ValueError from random.sample() deep inside the
        # variant-calling panel instead of a clean CLI error.
        r = run_cli("viz", "--out", "/tmp/should_not_be_written.html", "--genome-length", "100", "--seed", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
