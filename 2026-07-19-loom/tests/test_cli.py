"""CLI-level tests: verifies bad input produces a clean 'Error: ...' message
and exit code 1, never a raw Python traceback."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "loom.cli", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


class TestCLIErrorHandling(unittest.TestCase):
    def test_missing_checkpoint_gives_clean_error(self):
        result = run_cli("generate", "--ckpt", "/tmp/loom_test_does_not_exist_xyz", "--prompt", "hi", "-n", "5")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_dmodel_nheads_gives_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_cli("train", "--steps", "1", "--d-model", "65", "--n-heads", "4",
                              "--out", os.path.join(d, "ckpt"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error:", result.stderr)
        self.assertIn("d_model", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_corpus_too_short_for_block_size_gives_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path = os.path.join(d, "tiny.txt")
            with open(corpus_path, "w") as f:
                f.write("hi")
            result = run_cli("train", "--corpus", corpus_path, "--steps", "1",
                              "--block-size", "64", "--out", os.path.join(d, "ckpt"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_gradcheck_exits_zero(self):
        result = run_cli("gradcheck")
        self.assertEqual(result.returncode, 0)
        self.assertIn("26/26", result.stdout)


if __name__ == "__main__":
    unittest.main()
