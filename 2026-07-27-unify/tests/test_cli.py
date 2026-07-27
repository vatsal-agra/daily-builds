import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify import cli


class TestReadSource(unittest.TestCase):
    def test_missing_file_reports_clean_error_not_traceback(self):
        source, err = cli.read_source("/no/such/path/unify_test_missing.uy")
        self.assertIsNone(source)
        self.assertIn("cannot read", err)


class TestCheckAndRunSource(unittest.TestCase):
    def test_check_source_success(self):
        ok, out = cli.check_source("1 + 2")
        self.assertTrue(ok)
        self.assertIn("type: int", out)

    def test_run_source_success(self):
        ok, out = cli.run_source("1 + 2")
        self.assertTrue(ok)
        self.assertIn("type: int", out)
        self.assertIn("value: 3", out)

    def test_run_source_parse_error(self):
        ok, out = cli.run_source("let x = in x")
        self.assertFalse(ok)
        self.assertIn("error:", out)

    def test_run_source_type_error(self):
        ok, out = cli.run_source("1 + true")
        self.assertFalse(ok)
        self.assertIn("expected int, found bool", out)

    def test_run_source_eval_error(self):
        ok, out = cli.run_source("1 / 0")
        self.assertFalse(ok)
        self.assertIn("division by zero", out)

    def test_trace_includes_derivation(self):
        ok, out = cli.check_source("1 + 2", trace=True)
        self.assertTrue(ok)
        self.assertIn("--- derivation ---", out)
        self.assertIn("BinOp", out)

    def test_deep_recursion_reported_cleanly_not_a_raw_traceback(self):
        src = (
            "let rec sumto n = if n = 0 then 0 else n + sumto (n - 1) "
            "in sumto 500000"
        )
        ok, out = cli.run_source(src)
        self.assertFalse(ok)
        self.assertIn("recursion too deep", out)


if __name__ == "__main__":
    unittest.main()
