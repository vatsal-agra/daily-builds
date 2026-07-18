import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.cli import main

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestBuildCommand(unittest.TestCase):
    def test_build_and_search_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            index_path = os.path.join(d, "index.json")
            code, out, _ = run_cli(["build", os.path.join(FIXTURES, "corpus_a"), "--out", index_path])
            self.assertEqual(code, 0)
            self.assertIn("indexed 4 documents", out)

            code, out, _ = run_cli(["search", "fox", "--index", index_path])
            self.assertEqual(code, 0)
            self.assertIn("matches", out)

    def test_uppercase_extension_is_not_silently_ignored(self):
        # Regression: --ext TXT used to match zero files because the
        # scan lowercases filenames but never lowercased the user's
        # --ext value.
        with tempfile.TemporaryDirectory() as d:
            index_path = os.path.join(d, "index.json")
            code, out, err = run_cli([
                "build", os.path.join(FIXTURES, "corpus_a"),
                "--ext", "TXT", "--out", index_path,
            ])
            self.assertEqual(code, 0, msg=err)
            self.assertIn("indexed 4 documents", out)

    def test_empty_directory_reports_error_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run_cli(["build", d, "--out", os.path.join(d, "index.json")])
            self.assertEqual(code, 1)
            self.assertIn("files found", err)

    def test_search_without_prior_build_reports_error_not_crash(self):
        code, out, err = run_cli(["search", "fox", "--index", "/nonexistent/index.json"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_search_syntax_error_reports_error_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            index_path = os.path.join(d, "index.json")
            run_cli(["build", os.path.join(FIXTURES, "corpus_a"), "--out", index_path])
            code, out, err = run_cli(["search", "fox AND (lazy", "--index", index_path])
            self.assertEqual(code, 1)
            self.assertIn("query error", err)

    def test_negative_top_does_not_crash_or_misbehave(self):
        with tempfile.TemporaryDirectory() as d:
            index_path = os.path.join(d, "index.json")
            run_cli(["build", os.path.join(FIXTURES, "corpus_a"), "--out", index_path])
            code, out, err = run_cli(["search", "fox", "--index", index_path, "--top", "-1"])
            self.assertEqual(code, 0, msg=err)
            self.assertIn("no results", out)


if __name__ == "__main__":
    unittest.main()
