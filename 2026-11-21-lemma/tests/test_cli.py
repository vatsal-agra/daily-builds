import json
import os
import subprocess
import sys
import tempfile
import unittest
from tests.helpers import ROOT


def lemma(*args, stdin=None):
    p = subprocess.run([sys.executable, "-m", "lemma", *args], cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


class CLITests(unittest.TestCase):
    def test_check_ok(self):
        rc, out, err = lemma("check", "examples/nat.lm")
        self.assertEqual(rc, 0, err)
        self.assertIn("6 theorem(s) proved", out)
        self.assertIn("0 error(s)", out)

    def test_check_failing_file_exits_1_with_positions(self):
        rc, out, err = lemma("check", "examples/fail_demo.lm")
        self.assertEqual(rc, 1)
        self.assertIn("fail_demo.lm:6:", err)
        self.assertIn("not definitionally equal", err)
        self.assertIn("not strictly positive", err.replace("non-strictly-positive", "not strictly positive"))
        self.assertIn("unsolved goals", err)
        self.assertIn("did you mean 'succ'", err)
        self.assertIn("good_one", out)

    def test_missing_file(self):
        rc, out, err = lemma("check", "no_such_file.lm")
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", out + err)

    def test_export_audit_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            cert = os.path.join(d, "c.json")
            rc, out, err = lemma("check", "examples/even.lm", "--export", cert)
            self.assertEqual(rc, 0, err)
            rc, out, err = lemma("audit", cert)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("verified independently", out)
            data = json.load(open(cert))
            for dd in data["decls"]:
                if dd["name"] == "even_four":
                    dd["ty"] = ["const", "False"]
            json.dump(data, open(cert, "w"))
            rc, out, err = lemma("audit", cert)
            self.assertEqual(rc, 1)
            self.assertIn("REJECTED", out)

    def test_check_with_audit_flag(self):
        rc, out, err = lemma("check", "examples/trees.lm", "--audit")
        self.assertEqual(rc, 0, err)
        self.assertIn("auditor: ALL", out)

    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "r.html")
            rc, out, err = lemma("report", "examples/nat.lm", "-o", html)
            self.assertEqual(rc, 0, err)
            text = open(html, encoding="utf-8").read()
            self.assertIn("mul_add_l", text)
            self.assertIn("induction a as zero | succ k ih.", text)
            self.assertIn("verified", text)
            self.assertIn("prefers-color-scheme", text)
            rc, out, err = lemma("report", "examples/fail_demo.lm", "-o", html)
            self.assertEqual(rc, 1)
            self.assertIn("rejected", open(html, encoding="utf-8").read())

    def test_eval_subcommand(self):
        rc, out, err = lemma("eval", "6 * 7")
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("42 : Nat"))
        rc, out, err = lemma("eval", "nonsense")
        self.assertEqual(rc, 1)
        self.assertIn("unknown identifier", err)

    def test_repl(self):
        script = ("#eval 6 * 7\n"
                  "theorem t : 2 + 2 = 4 := by\n  refl.\n\n"
                  "#check t\n"
                  "def f (n : Nat) : Nat :=\n  elim n with\n  | zero => 1\n  | succ k ih => 2 * f k\n  end\n"
                  "#eval f 10\n"
                  "#eval oops\n"
                  ":axioms add_comm\n:names\n:bogus\n:quit\n")
        rc, out, err = lemma("repl", stdin=script)
        self.assertEqual(rc, 0, err)
        self.assertIn("42 : Nat", out)
        self.assertIn("theorem t : 2 + 2 = 4", out)
        self.assertIn("t : 2 + 2 = 4", out)
        self.assertIn("1024 : Nat", out)
        self.assertIn("unknown identifier 'oops'", out)
        self.assertIn("no axioms", out)
        self.assertIn("unknown meta-command :bogus", out)


if __name__ == "__main__":
    unittest.main()
