import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import rxlab
from rxlab.cli import main as cli_main
from rxlab.explain import explain
from rxlab.fuzz import run_fuzz
from rxlab.gen import generate
from rxlab.lexer import RegexCompileError
from rxlab.viz import build_data, render_html, write_html


class TestExplain(unittest.TestCase):
    def test_phrases(self):
        out = explain(r"(\d{1,3}\.){3}\d{1,3}|localhost")
        for needle in ["any one of", "exactly 3 of", "capture group 1",
                       "between 1 and 3", "a digit (0-9)",
                       "the text 'localhost'", "captures 1 group"]:
            self.assertIn(needle, out)

    def test_lazy_and_anchors(self):
        out = explain(r"^a+?\b$")
        self.assertIn("lazy", out)
        self.assertIn("start of the string", out)
        self.assertIn("word boundary", out)
        self.assertIn("end of the string", out)

    def test_empty_and_classes(self):
        self.assertIn("the empty string", explain(""))
        self.assertIn("any character NOT in", explain("[^xyz]"))


class TestGen(unittest.TestCase):
    def test_samples_all_match(self):
        for pat in [r"(\d{1,3}\.){3}\d{1,3}", r"\bcat\b", r"a(b|c)*d",
                    r"[A-Z][a-z]{2,5} \d+", r"^x$", r"(?:foo|bar)+"]:
            samples, _ = generate(pat, n=8, seed=7)
            self.assertTrue(samples, pat)
            p = rxlab.compile(pat)
            for s in samples:
                self.assertIsNotNone(p.fullmatch(s), f"{pat!r} -> {s!r}")

    def test_deterministic_per_seed(self):
        a, _ = generate(r"\w{3}-\d{2}", n=5, seed=11)
        b, _ = generate(r"\w{3}-\d{2}", n=5, seed=11)
        self.assertEqual(a, b)

    def test_distinct_samples(self):
        samples, _ = generate(r"[ab]{4}", n=10, seed=3)
        self.assertEqual(len(samples), len(set(samples)))

    def test_unsatisfiable_raises(self):
        with self.assertRaises(RegexCompileError):
            generate(r"a\bb", n=2)

    def test_single_possibility(self):
        samples, _ = generate(r"\bcat\b", n=5, seed=0)
        self.assertEqual(samples, ["cat"])


class TestFuzz(unittest.TestCase):
    def test_no_divergence_from_re(self):
        checked, diffs = run_fuzz(n=400, seed=20260612)
        self.assertEqual(checked, 400)
        self.assertEqual(diffs, [], "engine diverged from re")


class TestViz(unittest.TestCase):
    def test_build_data_structure(self):
        data = build_data(r"(a|b)*abb", sample="ababb")
        self.assertEqual(data["pattern"], r"(a|b)*abb")
        self.assertEqual(data["ngroups"], 1)
        self.assertEqual(data["prog"][-1]["op"], "match")
        self.assertEqual(len(data["dfa"]["trans"]), 4)  # textbook minimal

    def test_dfa_error_embedded_for_word_boundary(self):
        data = build_data(r"\bcat\b")
        self.assertIn("error", data["dfa"])

    def test_html_escapes_script_breakout(self):
        html = render_html("a</script><b>", sample="</script>")
        self.assertIn(r"a<\/script><b>", html)     # JSON-escaped form
        self.assertNotIn("a</script><b>", html)    # raw form would break out

    def test_write_html(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.html")
            write_html("ab+", path)
            with open(path, encoding="utf-8") as f:
                self.assertIn("REGEX", f.read())

    def test_size_cap(self):
        with self.assertRaises(RegexCompileError):
            build_data("a{600}")


class TestCli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_search_found_and_not_found(self):
        code, out, _ = self.run_cli("search", r"(\d+)", "abc 42")
        self.assertEqual(code, 0)
        self.assertIn("'42'", out)
        code, out, _ = self.run_cli("search", "z", "abc")
        self.assertEqual(code, 1)
        self.assertIn("no match", out)

    def test_parse_dfa_trace_findall(self):
        for argv in (["parse", "a(b|c)*"],
                     ["dfa", "(a|b)*abb", "--table", "--text", "abb"],
                     ["trace", "ab", "zab"],
                     ["findall", r"\d+", "a1b22"],
                     ["explain", "a+b"],
                     ["gen", "[ab]{2}", "-n", "3", "--seed", "1"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 0, (argv, err))
            self.assertTrue(out.strip(), argv)

    def test_bad_pattern_exit_2(self):
        code, _, err = self.run_cli("search", "a(", "x")
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_dashed_pattern_with_separator(self):
        code, out, _ = self.run_cli("search", "--", r"-\d+", "x-42")
        self.assertEqual(code, 0)
        self.assertIn("'-42'", out)
