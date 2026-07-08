import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
CLI = os.path.join(ROOT, "cli.py")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, CLI, *args], capture_output=True, text=True, cwd=ROOT
    )


class TestCLI(unittest.TestCase):
    def test_no_args_prints_usage_and_exits_nonzero(self):
        result = run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)

    def test_unknown_subcommand_prints_usage(self):
        result = run_cli("bogus-command")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)

    def test_missing_checkpoint_gives_clean_error_not_traceback(self):
        result = run_cli("generate", "--checkpoint-dir", "/tmp/loom_does_not_exist_xyz", "--prompt", "hi")
        self.assertEqual(result.returncode, 1)
        self.assertIn("error:", result.stderr)
        self.assertIn("Train a model first", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_tokenize_subcommand_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = os.path.join(d, "corpus.txt")
            with open(corpus, "w") as f:
                f.write("the quick brown fox jumps over the lazy dog. " * 20)
            out = os.path.join(d, "tok.json")
            result = run_cli(
                "tokenize", "--corpus", corpus, "--vocab-size", "270", "--out", out,
                "--text", "a brand new sentence",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(out))
            self.assertIn("decode(...)", result.stdout)

    def test_gradcheck_subcommand_runs_and_passes(self):
        result = run_cli("gradcheck")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
