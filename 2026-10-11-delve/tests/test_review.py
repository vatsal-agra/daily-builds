"""Regression tests for every finding in REVIEW.md (R1-R9)."""
import contextlib, io, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from delve import terms as tm
from delve.bitblast import Smt, Unknown
from delve.cli import main
from delve.interp import Interp
from delve.lang import DelveError, parse
from delve.report import text_report
from delve.symex import Explorer


def cli(args, src=None):
    """Run the CLI, return (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    path = None
    if src is not None:
        fd, path = tempfile.mkstemp(suffix=".dl"); os.write(fd, src.encode()); os.close(fd)
        args = [a if a != "@" else path for a in args]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(args)
    finally:
        if path: os.unlink(path)
    return rc, out.getvalue(), err.getvalue()


class ReviewTests(unittest.TestCase):
    def test_r1_literal_overflow_rejected(self):
        rc, out, err = cli(["run", "@"], "let y = 300;\nreturn y;")
        self.assertEqual(rc, 64); self.assertIn("literal 300 does not fit in 8 bits", err); self.assertIn("line 1", err)
        rc, out, _ = cli(["run", "@", "--width", "16"], "return 300;")
        self.assertEqual((rc, out.strip()), (0, "returned 300"))
        with self.assertRaises(DelveError): Explorer(parse("return 1000;"), 8)
        Interp(parse("return 0xFF;"), 8).run({})        # 255 fits as an unsigned bit pattern

    def test_r2_else_if_does_not_reevaluate_calls(self):
        src = "fn f(n) { print(n); return n; }\nlet x = input(0, 9);\nif (f(x) > 100) { } else if (x > 5) { print(99); }"
        r = Interp(parse(src), 8).run({"x": 7})
        self.assertEqual(r.outputs, [7, 99])
        ex = Explorer(parse(src), 8).explore(); self.assertTrue(ex.verify())

    def test_r3_verdict_wording(self):
        ex = Explorer(parse("let a = input(); if (a > 3) { return 1; }"), 8).explore(); ex.verify()
        self.assertIn("exhaustive", text_report(ex))
        self.assertNotIn("loop bound", text_report(ex).split("BUGS")[0].split("coverage")[-1])
        ex = Explorer(parse("let n = input(0, 100); let i = 0; while (i < n) { i = i + 1; }"), 8, loop_bound=3).explore(); ex.verify()
        t = text_report(ex)
        self.assertIn("NOT a proof", t); self.assertIn("cut at the loop/call bound", t)

    def test_r4_solver_budget_gives_unknown_not_hang(self):
        # factoring-style query is hard at 32 bits; a tiny budget must give up cleanly
        smt = Smt(budget=50)
        a, b = tm.var("a", 32), tm.var("b", 32)
        hard = [tm.eq(tm.mul(a, b), tm.const(1000000007 * 998244353 & 0xFFFFFFFF, 32)),
                tm.ult(tm.const(1, 32), a), tm.ult(tm.const(1, 32), b),
                tm.ult(a, tm.const(65536, 32)), tm.ult(b, tm.const(65536, 32))]
        with self.assertRaises(Unknown): smt.check(hard)
        ex = Explorer(parse("let a = input(); let b = input(); if (a * b == 123456789 && a > 1 && b > 1 && a < 30000 && b < 30000) { assert(0); }"),
                      32, solver_budget=20, minimize=False).explore()
        self.assertGreater(ex.unknown, 0)
        self.assertIn("abandoned", text_report(ex))

    def test_r5_deep_expression(self):
        src = "let x = 1; return " + "+".join(["x"] * 3000) + ";"
        rc, out, err = cli(["run", "@", "--width", "16"], src)
        self.assertEqual((rc, out.strip()), (0, "returned 3000"), err)

    def test_r6_unknown_input_warns(self):
        rc, out, err = cli(["run", "@", "-i", "zz=4"], "let a = input(); return a;")
        self.assertIn("unknown input name(s) zz", err); self.assertIn("this run reads: a", err)

    def test_r7_no_feasible_paths_explained(self):
        rc, out, err = cli(["analyze", "@"], "assume(0);")
        self.assertIn("no feasible execution exists", out)
        rc, out, err = cli(["analyze", "@"], "let x = input(5, 1); return x;")
        self.assertIn("no feasible execution exists", out)

    def test_r8_readable_conditions(self):
        ex = Explorer(parse("let n = input(); if (n < 0) { return 0 - n; } return n;"), 8).explore(); ex.verify()
        t = text_report(ex)
        self.assertNotIn("ite(", t); self.assertNotIn("0 ==", t)
        self.assertIn("(n < 0)", t)

    def test_r9_inputs_inside_loops(self):
        src = "let n = input(0, 3); let i = 0; let t = 0;\nwhile (i < n) { let v = input(0, 9); t = t + v; i = i + 1; }\nassert(t != 13);"
        ex = Explorer(parse(src), 8, loop_bound=4).explore()
        self.assertTrue(ex.verify())
        b = ex.bugs[("assertion failure", 3)]
        self.assertEqual(b.in_names[:2], ["n", "v"]); self.assertIn("v#3", b.in_names)
        vals = [b.inputs[k] for k in b.in_names[1:]]
        self.assertEqual(sum(vals), 13)

    def test_output_flags_and_exit_codes(self):
        rc, out, _ = cli(["analyze", "@", "-q"], "let a = input(); assert(a != 7);")
        self.assertEqual(rc, 1); self.assertIn("a=7", out)
        rc, out, _ = cli(["analyze", "@", "-q"], "let a = input(); return a;")
        self.assertEqual(rc, 0)
        rc, _, err = cli(["run", "/nonexistent.dl"]); self.assertEqual(rc, 64); self.assertIn("cannot read", err)
        rc, _, err = cli(["run", "@", "--width", "99"], "return 1;"); self.assertEqual(rc, 64)


if __name__ == "__main__":
    unittest.main()
