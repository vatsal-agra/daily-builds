import itertools, os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from delve import terms as tm
from delve.interp import Interp
from delve.lang import parse, DelveError
from delve.symex import Explorer

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def read(name):
    with open(os.path.join(EX, name)) as f:
        return f.read()


def explore(src, w=8, **kw):
    ex = Explorer(parse(src), w, **kw).explore()
    return ex


class InterpTests(unittest.TestCase):
    def run_src(self, src, inputs=None, w=8):
        return Interp(parse(src), w).run(inputs or {})

    def test_arith_wrap_and_return(self):
        r = self.run_src("let a = 100; let b = a & 0xFF; return b ^ 5;")
        self.assertEqual(r.value, 100 ^ 5)
        self.assertIsNone(r.trap)

    def test_overflow_trap(self):
        r = self.run_src("let a = 100; let b = a + a;")
        self.assertEqual(r.trap, ("signed overflow", 1))

    def test_div_zero_and_minint(self):
        self.assertEqual(self.run_src("let a = 0; return 5 / a;").trap, ("division by zero", 1))
        self.assertEqual(self.run_src("let a = -128; return a / -1;").trap, ("signed overflow", 1))
        self.assertEqual(self.run_src("return -7 / 2;").value & 255, (-3) & 255)     # truncation toward zero
        self.assertEqual(self.run_src("return -7 % 2;").value & 255, (-1) & 255)

    def test_shifts(self):
        self.assertEqual(self.run_src("return -8 >> 1;").value & 255, (-4) & 255)
        self.assertEqual(self.run_src("return -8 >>> 1;").value, 0x7c)
        self.assertEqual(self.run_src("let s = 8; return 1 << s;").trap, ("invalid shift", 1))

    def test_functions_recursion_and_loops(self):
        src = "fn fact(n) { if (n <= 1) { return 1; } return n * fact(n - 1); } return fact(5);"
        self.assertEqual(self.run_src(src, w=16).value, 120)
        self.assertEqual(self.run_src("let i = 0; let s = 0; while (i < 10) { i = i + 1; s = s + i; } return s;").value, 55)

    def test_infinite_loop_budget(self):
        r = Interp(parse("while (1) { }"), 8, max_steps=500).run({})
        self.assertTrue(r.exhausted)

    def test_assume_and_input_range(self):
        self.assertTrue(self.run_src("let x = input(0, 5);", {"x": 9}).infeasible)
        self.assertFalse(self.run_src("let x = input(0, 5);", {"x": 3}).infeasible)
        self.assertTrue(self.run_src("assume(0);").infeasible)

    def test_parse_errors(self):
        for bad in ("let = 3;", "return y;", "let x = 1", "let x = input() + 1;", "f(1);",
                    "fn f(a){return a;} let x = f(1,2);", "let a = 1; while (f(a)) {}", "let x = 5 $ 3;"):
            with self.assertRaises(DelveError, msg=bad): parse(bad)


class SymexTests(unittest.TestCase):
    def test_path_enumeration_and_tests_replay(self):
        ex = explore("let x = input(); if (x > 10) { if (x < 20) { return 1; } return 2; } return 3;")
        self.assertEqual(len(ex.paths), 3)
        self.assertTrue(ex.verify())
        rets = sorted(p.expected_ret for p in ex.paths)
        self.assertEqual(rets, [1, 2, 3])

    def test_infeasible_paths_pruned(self):
        ex = explore("let x = input(); if (x > 5) { if (x < 3) { return 1; } return 2; } return 3;")
        self.assertEqual(len(ex.paths), 2)
        ex.verify()
        self.assertEqual(sorted(p.expected_ret for p in ex.paths), [2, 3])

    def test_assert_violation_found_with_witness(self):
        ex = explore("let x = input(); let y = x * 3 + 1; assert(y != 22);")
        self.assertIn(("assertion failure", 1), ex.bugs)
        self.assertTrue(ex.verify())
        x = ex.bugs[("assertion failure", 1)].inputs["x"]
        self.assertEqual((x * 3 + 1) & 255, 22)

    def test_div_zero_overflow_shift_found(self):
        ex = explore("let a = input(); let b = input(); let c = a / b; let d = a + b; let e = 1 << a;")
        kinds = {k for k, _ in ex.bugs}
        self.assertEqual(kinds, {"division by zero", "signed overflow", "invalid shift"})
        self.assertTrue(ex.verify())

    def test_no_false_positive_on_guarded_code(self):
        ex = explore("let a = input(); let b = input(); if (b != 0 && !(a == -128 && b == -1)) { return a / b; } return 0;")
        self.assertEqual(ex.bugs, {})
        self.assertTrue(ex.verify())

    def test_short_circuit_guards_checks(self):
        ex = explore("let a = input(); let b = input(); return b > 0 && a / b > 1;")
        self.assertEqual(ex.bugs, {})
        ex = explore("let a = input(); let b = input(); return b != 0 || a / b > 1;")
        self.assertIn(("division by zero", 1), ex.bugs)

    def test_loops_bounded_and_truncation_reported(self):
        ex = explore("let n = input(0, 100); let i = 0; while (i < n) { i = i + 1; }", loop_bound=4)
        self.assertEqual(len(ex.paths), 5)
        self.assertEqual(ex.truncated, 1)
        self.assertTrue(ex.verify())

    def test_function_calls_and_recursion(self):
        src = "fn g(a) { if (a > 5) { return a - 5; } return g(a + 4); } let x = input(0, 20); return g(x);"
        ex = explore(src, w=8)
        self.assertTrue(ex.verify())
        self.assertGreaterEqual(len(ex.paths), 3)

    def test_assume_restricts_paths(self):
        ex = explore("let x = input(); assume(x > 100); if (x > 50) { return 1; } return 2;")
        ex.verify()
        self.assertEqual([p.expected_ret for p in ex.paths if p.ret is not None], [1])

    def test_examples(self):
        for name, want in (("abs.dl", {("signed overflow", 2)}), ("safe_sum.dl", set())):
            ex = Explorer(parse(read(name)), 16 if "sum" in name else 8).explore()
            self.assertTrue(ex.verify(), name)
            self.assertEqual(set(ex.bugs), want, name)
        ex = Explorer(parse(read("triage.dl")), 8).explore()
        self.assertEqual(set(ex.bugs), {("division by zero", 15)})
        self.assertEqual(ex.bugs[("division by zero", 15)].inputs["age"], 5)
        self.assertTrue(ex.verify())

    def test_width_changes_bugs(self):
        src = "let x = input(); let y = x + 100; return y;"
        self.assertIn(("signed overflow", 1), explore(src, 8).bugs)
        self.assertEqual(explore(src, 16).bugs.get(("signed overflow", 1)).inputs["x"], 32668)


GEN_OPS = ["+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", ">>>", "<", "<=", "==", "!=", ">", ">="]


def gen_expr(rnd, vars_, depth):
    if depth == 0 or rnd.random() < .3:
        return rnd.choice(vars_) if rnd.random() < .7 else str(rnd.randint(-6, 9))
    r = rnd.random()
    if r < .1: return "(%s%s)" % (rnd.choice(["-", "~", "!"]), gen_expr(rnd, vars_, depth - 1))
    if r < .2: return "(%s ? %s : %s)" % tuple(gen_expr(rnd, vars_, depth - 1) for _ in range(3))
    if r < .3: return "(%s %s %s)" % (gen_expr(rnd, vars_, depth - 1), rnd.choice(["&&", "||"]), gen_expr(rnd, vars_, depth - 1))
    return "(%s %s %s)" % (gen_expr(rnd, vars_, depth - 1), rnd.choice(GEN_OPS), gen_expr(rnd, vars_, depth - 1))


def gen_program(rnd):
    lines = ["let x = input();", "let y = input();"]
    vs = ["x", "y"]
    for i in range(rnd.randint(2, 4)):
        v = "v%d" % i
        r = rnd.random()
        if r < .55:
            lines.append("let %s = %s;" % (v, gen_expr(rnd, vs, 2))); vs.append(v)
        elif r < .8:
            lines.append("let %s = 0; if (%s) { %s = %s; } else { %s = %s; }" % (v, gen_expr(rnd, vs, 2), v, gen_expr(rnd, vs, 1), v, gen_expr(rnd, vs, 1))); vs.append(v)
        elif r < .9:
            lines.append("assert(%s);" % gen_expr(rnd, vs, 2))
        else:
            lines.append("let k%d = %s & 3; let c%d = 0; while (c%d < k%d) { c%d = c%d + 1; x = x + c%d; }" % ((i,) * 8))
    lines.append("print(%s);" % rnd.choice(vs))
    lines.append("return %s;" % gen_expr(rnd, vs, 2))
    return "\n".join(lines)


class FuzzTests(unittest.TestCase):
    """For random programs and EVERY input pair, exactly one symbolic path must match,
    and its predicted outcome must equal what the concrete interpreter does."""

    def test_paths_partition_input_space(self):
        rnd = random.Random(2026)
        W = 5
        grid = list(itertools.product(range(1 << W), repeat=2))
        for n in range(25):
            src = gen_program(rnd)
            prog = parse(src)
            ex = Explorer(prog, W, loop_bound=8).explore()
            self.assertIsNone(ex.hit_limit, src)
            self.assertEqual(ex.truncated, 0, src)
            it = Interp(prog, W)
            for x, y in grid:
                env = {"x": x, "y": y}
                res = it.run(env)
                if res.infeasible: continue
                hits = [p for p in ex.paths if all(tm.evaluate(c, env) == 1 for c in p.pc)]
                self.assertEqual(len(hits), 1, "program:\n%s\ninput x=%d y=%d matched %d paths" % (src, x, y, len(hits)))
                p = hits[0]
                if p.status == "error":
                    self.assertEqual(res.trap, p.trap, (src, env))
                else:
                    self.assertIsNone(res.trap, (src, env))
                    self.assertEqual(res.value, tm.evaluate(p.ret, env), (src, env))
                    self.assertEqual(res.outputs, [tm.to_signed(tm.evaluate(o, env), W) for o in p.outputs], (src, env))
            self.assertTrue(ex.verify(), src)


if __name__ == "__main__":
    unittest.main()
