import contextlib, io, os, sys, tempfile, unittest, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from delve.cli import main
from delve.extras import check_equiv, solve_formula
from delve.lang import parse, DelveError

EQ = os.path.join(os.path.dirname(__file__), "..", "examples", "equiv")


def prog(name):
    with open(os.path.join(EQ, name)) as f: return parse(f.read())


def cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(args)
    return rc, out.getvalue(), err.getvalue()


class EquivTests(unittest.TestCase):
    def test_equivalent_pairs(self):
        for a, b in (("abs_branch.dl", "abs_trick.dl"), ("mul_shift_a.dl", "mul_shift_b.dl"), ("clamp_a.dl", "clamp_b.dl")):
            r = check_equiv(prog(a), prog(b), 8)
            self.assertTrue(r.equivalent, (a, b)); self.assertTrue(r.complete)

    def test_distinguishing_input_is_real(self):
        r = check_equiv(prog("clamp_a.dl"), prog("clamp_buggy.dl"), 8)
        self.assertFalse(r.equivalent)
        self.assertTrue(r.cex["confirmed"])
        x = r.cex["inputs"]["x"]
        self.assertIn(x if x < 128 else x - 256, (0, 101, 100 + 1) + tuple(range(101, 128)))

    def test_trap_difference_detected(self):
        a = parse("let x = input(); return x;")
        b = parse("let x = input(); assert(x != 5); return x;")
        r = check_equiv(a, b, 8)
        self.assertFalse(r.equivalent); self.assertEqual(r.cex["inputs"]["x"], 5)

    def test_print_difference_detected(self):
        r = check_equiv(parse("let x = input(); print(x); return 0;"), parse("let x = input(); print(x + 1); return 0;"), 8)
        self.assertFalse(r.equivalent)

    def test_loop_vs_closed_form(self):
        a = parse("let n = input(0, 6); let i = 0; let s = 0; while (i < n) { i = i + 1; s = s + i; } return s;")
        b = parse("let n = input(0, 6); return n * (n + 1) / 2;")
        self.assertTrue(check_equiv(a, b, 8, loop_bound=8).equivalent)
        b2 = parse("let n = input(0, 6); return n * (n + 1) / 2 + (n == 4);")
        self.assertFalse(check_equiv(a, b2, 8, loop_bound=8).equivalent)

    def test_cli_exit_codes(self):
        rc, out, _ = cli(["equiv", os.path.join(EQ, "clamp_a.dl"), os.path.join(EQ, "clamp_b.dl")]); self.assertEqual(rc, 0); self.assertIn("EQUIVALENT", out)
        rc, out, _ = cli(["equiv", os.path.join(EQ, "clamp_a.dl"), os.path.join(EQ, "clamp_buggy.dl")]); self.assertEqual(rc, 1); self.assertIn("NOT EQUIVALENT", out)


class SolveTests(unittest.TestCase):
    def test_sat_model_satisfies(self):
        v, ms, names = solve_formula("x*3 + y == 42 && x < y", 8)
        self.assertEqual(v, "sat")
        m = ms[0]; sx = lambda t: t - 256 if t > 127 else t
        x, y = sx(m["x"]), sx(m["y"])
        self.assertTrue((x * 3 + y) % 256 == 42 and x < y)

    def test_unsat_and_valid_and_invalid(self):
        self.assertEqual(solve_formula("x*x == 2", 8)[0], "unsat")
        self.assertEqual(solve_formula("(x ^ y) + 2*(x & y) == x + y", 10, prove=True)[0], "valid")
        v, ms, _ = solve_formula("x + 1 > x", 8, prove=True)
        self.assertEqual((v, ms[0]["x"]), ("invalid", 127))

    def test_enumeration_distinct(self):
        v, ms, _ = solve_formula("x > 120", 8, count=10)
        vals = sorted(m["x"] for m in ms)
        self.assertEqual(sorted(vals), [121, 122, 123, 124, 125, 126, 127])
        self.assertEqual(len(set(vals)), len(vals))
        v, ms, _ = solve_formula("x > 124 && x <= 127", 8, count=10)
        self.assertEqual(sorted(m["x"] for m in ms), [125, 126, 127])

    def test_errors(self):
        for bad in ("x +", "x == == 1", "x == 1 2", "f(x)", "x == 5000", "x == 128"):
            with self.assertRaises(DelveError, msg=bad): solve_formula(bad, 8)

    def test_division_guarded(self):
        v, ms, _ = solve_formula("x / y == 3", 8)
        self.assertEqual(v, "sat"); self.assertNotEqual(ms[0]["y"], 0)


class HtmlAndTestsFile(unittest.TestCase):
    def test_html_and_json_outputs_and_replay(self):
        ex = os.path.join(os.path.dirname(__file__), "..", "examples", "triage.dl")
        with tempfile.TemporaryDirectory() as d:
            h, j = os.path.join(d, "r.html"), os.path.join(d, "t.json")
            rc, out, _ = cli(["analyze", ex, "--html", h, "--tests", j, "-q"])
            self.assertEqual(rc, 1)
            with open(h) as f: page = f.read()
            self.assertIn("<!doctype html>", page); self.assertIn("division by zero", page); self.assertIn("replay-confirmed", page)
            self.assertNotIn("<script", page)
            with open(j) as f: spec = json.load(f)
            self.assertEqual(len(spec["tests"]), 12)
            rc, out, _ = cli(["replay", ex, j]); self.assertEqual(rc, 0); self.assertIn("12/12 passed", out)
            spec["tests"][0]["expect"] = {"return": 77, "prints": []}
            with open(j, "w") as f: json.dump(spec, f)
            rc, out, _ = cli(["replay", ex, j]); self.assertEqual(rc, 1); self.assertIn("FAIL", out)

    def test_html_escapes_source(self):
        from delve.symex import Explorer
        from delve.report import html_report
        src = 'let a = input(); // <img src=x onerror=alert(1)>\nassert(a != 1);'
        ex = Explorer(parse(src), 8).explore(); ex.verify()
        self.assertNotIn("<img", html_report(ex, "<b>name</b>"))


if __name__ == "__main__":
    unittest.main()
