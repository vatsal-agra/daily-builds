import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run_cli(*args):
    result = subprocess.run(
        [sys.executable, "-m", "glean.cli", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


class TestCliIntegration(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glean_test_cli_")
        with open(os.path.join(self.root, "a.md"), "w", encoding="utf-8") as f:
            f.write("# Raft\nA raft consensus write-up with a bloom filter.")
        with open(os.path.join(self.root, "b.md"), "w", encoding="utf-8") as f:
            f.write("# Chess\nA chess engine article about transposition tables.")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_index_command(self):
        result = run_cli("index", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Indexed 2 document", result.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".glean")))

    def test_index_on_missing_directory_fails_cleanly(self):
        result = run_cli("index", os.path.join(self.root, "does-not-exist"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", result.stderr)

    def test_search_before_index_fails_cleanly(self):
        result = run_cli("search", "raft", "--dir", self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", result.stderr)

    def test_search_json_output(self):
        run_cli("index", self.root)
        result = run_cli("search", "bloom filter", "--dir", self.root, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["path"], "a.md")

    def test_search_boolean_and_phrase(self):
        run_cli("index", self.root)
        result = run_cli("search", "chess AND transposition", "--dir", self.root, "--json")
        payload = json.loads(result.stdout)
        self.assertEqual([r["path"] for r in payload["results"]], ["b.md"])

    def test_search_no_results_message(self):
        run_cli("index", self.root)
        result = run_cli("search", "zzznotarealwordzzz", "--dir", self.root, "--no-fuzzy")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No results", result.stdout)

    def test_stats_command(self):
        run_cli("index", self.root)
        result = run_cli("stats", "--dir", self.root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("documents:     2", result.stdout)

    def test_incremental_reindex_via_cli(self):
        run_cli("index", self.root)
        result = run_cli("index", self.root)
        self.assertIn("2 unchanged/reused", result.stdout)


if __name__ == "__main__":
    unittest.main()
