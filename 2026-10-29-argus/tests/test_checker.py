import json
import os
import random
import unittest
from types import SimpleNamespace

from argus.lang import ArgusError
from argus.live import check_ltl
from argus.model import build, successors
from argus.safety import check_safety
from argus.trace import (STUTTER, Trace, ValidationError, Violation, render, to_json, trace_from_json,
                         validate)
from tests.gen import rand_loop_program, rand_program

MODELS = os.path.join(os.path.dirname(__file__), "..", "models")


def mk(src, **kw):
    return build(src, kw)


class SafetyTests(unittest.TestCase):
    def test_shortest_counterexample(self):
        # x reaches 5 only via 5 increments; BFS must return exactly that, not a longer interleaving
        m = mk("var x = 0; proc A() { loop { x = x + 1; } } proc B() { loop { x = x + 1; } }"
               " run A(); run B(); invariant small: x < 5;")
        r = check_safety(m)
        self.assertEqual(len(r.violations), 1)
        self.assertEqual(len(r.violations[0].trace.steps), 5)

    def test_all_violation_kinds(self):
        for name, kind in [("lost_update", "assert"), ("flag_deadlock", "deadlock"), ("errors", "error"),
                           ("mutex_race", "invariant")]:
            m = build(open(f"{MODELS}/{name}.arg").read())
            r = check_safety(m)
            self.assertEqual(r.violations[0].kind, kind, name)
            validate(m, r.violations[0])

    def test_find_all_reports_each_property(self):
        src = """var x = 0; var y = 0;
        proc A() { x = 1; y = 1; assert x == 5, "boom"; }
        run A();
        invariant ix: x == 0; invariant iy: y == 0;"""
        m = mk(src)
        r = check_safety(m, find_all=True)
        names = sorted(v.name for v in r.violations)
        self.assertEqual(len([v for v in r.violations if v.kind == "invariant"]), 2, names)
        self.assertTrue(any(v.kind == "assert" for v in r.violations))
        for v in r.violations:
            validate(m, v)

    def test_end_labels_make_idle_states_valid(self):
        m = mk("chan q[1]; proc S() { loop { label end_wait: var_dummy_never = 0; } } run S();") if False else mk(
            "chan q[1]; proc S() { var x = 0; loop { label end_wait: recv(q, x); } } run S();")
        self.assertTrue(check_safety(m).ok)
        m = mk("chan q[1]; proc S() { var x = 0; loop { label wait: recv(q, x); } } run S();")
        self.assertEqual(check_safety(m).violations[0].kind, "deadlock")

    def test_state_limit_is_inconclusive_not_ok(self):
        m = mk("var x = 0; proc P() { loop { x = x + 1; } } run P();")
        r = check_safety(m, max_states=100)
        self.assertTrue(r.limited)
        self.assertFalse(r.ok)

    def test_invariant_evaluation_error_is_replayable(self):
        m = mk("var a[2] = 0; proc P() { skip; } run P(); invariant bad: a[5] > 0;")
        r = check_safety(m)
        self.assertEqual(r.violations[0].kind, "error")
        validate(m, r.violations[0])

    def test_c_style_division_and_modulo(self):
        m = mk("var q = 0; var r = 0; proc P() { q = (0 - 7) / 2; r = (0 - 7) % 2; } run P();"
               " invariant never: q == (0 - 3) && r == (0 - 1) && at(P0, end_x);".replace(" && at(P0, end_x)", ""))
        r = check_safety(m)
        self.assertEqual(r.violations[0].kind, "invariant")   # reached q=-3, r=-1 (truncating division)

    def test_por_matches_full_search_on_random_programs(self):
        rng = random.Random(7)
        reduced_total = full_total = 0
        for i in range(250):
            src = rand_program(rng)
            m = build(src)
            full = check_safety(m, find_all=True, max_states=200000)
            red = check_safety(m, find_all=True, por=True, max_states=200000)
            self.assertFalse(full.limited or red.limited)
            kinds = lambda r: sorted({(v.kind) for v in r.violations})
            self.assertEqual(kinds(full), kinds(red), src)
            self.assertEqual({v.name for v in full.violations}, {v.name for v in red.violations}, src)
            self.assertLessEqual(red.states, full.states)
            full_total += full.states
            reduced_total += red.states
            for v in red.violations:
                validate(m, v)
        self.assertLess(reduced_total, full_total)   # POR actually reduces something


class PorTests(unittest.TestCase):
    def test_cycle_proviso_prevents_ignoring(self):
        # A spins on local state forever; without the proviso POR would always pick A and never run B
        src = """var g = 0;
        proc A() { var a = 0; loop { a = 1 - a; } }
        proc B() { g = 1; assert g == 0, "ignored"; }
        run A(); run B();"""
        m = build(src)
        self.assertEqual(check_safety(m).violations[0].kind, "assert")
        r = check_safety(m, por=True)
        self.assertEqual(r.violations[0].kind, "assert")
        validate(m, r.violations[0])

    def test_processes_observed_by_properties_are_not_reduced(self):
        src = """proc P() { var t = 0; t = 1; label here: t = 2; }
        proc Q() { var u = 0; u = 1; label there: u = 2; }
        run P(); run Q();
        invariant both: !(at(P0, here) && at(Q0, there));"""
        m = build(src)
        self.assertEqual(check_safety(m).violations[0].kind, "invariant")
        self.assertEqual(check_safety(m, por=True).violations[0].kind, "invariant")

    def test_local_only_processes_collapse(self):
        src = "proc P() { var a = 0; a = 1; a = 2; a = 3; } run P(); run P(); run P();"
        m = build(src)
        full, red = check_safety(m), check_safety(m, por=True)
        self.assertEqual(full.states, 4 ** 3)
        self.assertLess(red.states, 20)
        self.assertTrue(red.ok)


class CompileErrorTests(unittest.TestCase):
    def bad(self, src, frag):
        with self.assertRaises(ArgusError) as cm:
            build(src)
        self.assertIn(frag, str(cm.exception))

    def test_errors(self):
        self.bad("var x = 0;", "no 'run'")
        self.bad("proc P() { x = 1; } run P();", "undefined variable 'x'")
        self.bad("var x = 0; proc P(a, a) { skip; } run P(1, 2);", "duplicate parameter")
        self.bad("var x = 0; proc P() { skip; } run P(1);", "takes 0")
        self.bad("var x = 0; proc P() { skip; } run Q();", "unknown process")
        self.bad("var x[2] = 0; proc P() { x = 1; } run P();", "needs an index")
        self.bad("var x = 0; proc P() { x[1] = 1; } run P();", "not a global array")
        self.bad("var x = 0; var x = 1; proc P() { skip; } run P();", "declared twice")
        self.bad("const N = 2; proc P() { N = 3; } run P();", "constant")
        self.bad("var x = 0; proc P() { break; } run P();", "outside of a loop")
        self.bad("var x = 0; proc P() { atomic { loop { x = 1; } } } run P();", "not allowed inside atomic")
        self.bad("var x = 0; proc P() { atomic { x = 1; recv(q, x); } } run P();", "")
        self.bad("var x = 0; proc P() { skip; } run P(); invariant i: at(P0, nope) == 1;", "no label")
        self.bad("var x = 0; proc P() { skip; } run P(); ltl a: <> x == 1; ltl a: [] x == 1;", "duplicate property")
        self.bad("var x : 3..1 = 0; proc P() { skip; } run P();", "empty range")
        self.bad("var x : 0..2 = 5; proc P() { skip; } run P();", "outside")
        self.bad("proc P() { var t = 0; t = 1 } run P();", "expected ';'")
        self.bad("var x = 0; proc P() { x = 1; } run P(); run P() as P0;", "not unique")
        self.bad("chan q[0]; proc P() { skip; } run P();", "capacity")

    def test_error_has_line_and_caret(self):
        try:
            build("var x = 0;\nproc P() {\n  x = ;\n}\nrun P();")
        except ArgusError as ex:
            s = str(ex)
            self.assertIn("line 3", s)
            self.assertIn("^", s)
        else:
            self.fail("no error")

    def test_define_override(self):
        src = "const N = 2; var a[N] = 0; proc P() { skip; } run P();"
        self.assertEqual(len(build(src).init), 2 + 1)
        self.assertEqual(len(build(src, {"N": 5}).init), 5 + 1)
        with self.assertRaises(ArgusError):
            build(src, {"M": 1})


class TraceTests(unittest.TestCase):
    def test_json_round_trip_and_replay(self):
        for name in ["abp", "lost_update", "philosophers"]:
            m = build(open(f"{MODELS}/{name}.arg").read())
            if name == "abp":
                m.invariants = []
                spec = m.ltls[0]
                r = check_ltl(m, spec, "weak", "proc")
                v = r.violation
                v.fairness, v.granularity = "weak", "proc"
            else:
                v = check_safety(m).violations[0]
            d = json.loads(json.dumps(to_json(m, v)))
            v2 = trace_from_json(m, d)
            validate(m, v2, "weak", "proc")

    def test_validator_rejects_tampered_traces(self):
        m = build(open(f"{MODELS}/lost_update.arg").read())
        v = check_safety(m).violations[0]
        good = v.trace
        # 1. drop a step
        bad = Trace(good.init, good.steps[:3] + good.steps[4:], fail=good.fail)
        with self.assertRaises(ValidationError):
            validate(m, Violation(v.kind, v.name, v.message, bad))
        # 2. swap two steps of different processes so the second is not enabled/consistent
        steps = list(good.steps)
        steps[0], steps[-1] = steps[-1], steps[0]
        with self.assertRaises(ValidationError):
            validate(m, Violation(v.kind, v.name, v.message, Trace(good.init, steps, fail=good.fail)))
        # 3. corrupt a recorded state
        pid, e, st = good.steps[2]
        st = list(st)
        st[0] += 7
        steps = list(good.steps)
        steps[2] = (pid, e, tuple(st))
        with self.assertRaises(ValidationError):
            validate(m, Violation(v.kind, v.name, v.message, Trace(good.init, steps, fail=good.fail)))
        # 4. claim a violation that is not one
        ok_model = build(open(f"{MODELS}/lost_update_fixed.arg").read())
        with self.assertRaises(ValidationError):
            validate(ok_model, Violation("deadlock", "deadlock", "", Trace(ok_model.init, [])))

    def test_render_mentions_every_step(self):
        m = build(open(f"{MODELS}/philosophers.arg").read())
        v = check_safety(m).violations[0]
        text = render(m, v)
        self.assertEqual(text.count("atomic {"), 3)
        self.assertIn("deadlock", text)


class LiveTests(unittest.TestCase):
    def verdicts(self, m, spec):
        return [check_ltl(m, spec, f, "proc").ok for f in ("none", "weak", "strong")]

    def test_fairness_is_monotone_on_models(self):
        for name in ["peterson", "fairness_ladder", "prodcons", "philosophers_ordered", "twophase"]:
            m = build(open(f"{MODELS}/{name}.arg").read())
            for spec in m.ltls:
                a, b, c = self.verdicts(m, spec)
                self.assertTrue((not a) or b, (name, spec.name))     # holds w/o fairness => holds weakly
                self.assertTrue((not b) or c, (name, spec.name))     # weak => strong

    def test_fairness_ladder_exact(self):
        m = build(open(f"{MODELS}/fairness_ladder.arg").read())
        spec = {s.name: s for s in m.ltls}
        self.assertEqual(self.verdicts(m, spec["done2"]), [False, True, True])
        self.assertEqual(self.verdicts(m, spec["done1"]), [False, False, True])

    def test_edge_fairness_differs_from_process_fairness(self):
        # A process that can either make progress or spin: process-fairness is satisfied by spinning
        src = """var done = 0;
        proc P() { loop { either { skip; } or { done = 1; } } }
        run P(); ltl d: <> (done == 1);"""
        m = build(src)
        spec = m.ltls[0]
        self.assertFalse(check_ltl(m, spec, "weak", "proc").ok)
        self.assertTrue(check_ltl(m, spec, "weak", "edge").ok)

    def test_runtime_error_during_liveness_is_reported(self):
        m = build("var a[2] = 0; proc P() { a[3] = 1; } run P(); ltl l: <> (a[0] == 1);")
        r = check_ltl(m, m.ltls[0])
        self.assertIsNotNone(r.error)

    def test_atom_error_is_a_clean_error(self):
        m = build("var v[2] = 0; proc P() { skip; } run P(); ltl l: <> (v[3] == 1);")
        with self.assertRaises(ArgusError):
            check_ltl(m, m.ltls[0])

    def test_liveness_vs_bruteforce(self):
        """If an exhaustive search over short fair lassos finds a violation, the checker must too."""
        from tests.test_ltl import rand_formula
        rng = random.Random(99)
        found_violations = 0
        for trial in range(150):
            m = build(rand_loop_program(rng))
            xs, ys, zs = m.vars["x"].base, m.vars["y"].base, m.vars["z"].base
            atoms = [("x==1", lambda s, i=xs: s[i] == 1), ("y==1", lambda s, i=ys: s[i] == 1),
                     ("z==1", lambda s, i=zs: s[i] == 1)]
            f = rand_formula(rng, 3)
            spec = SimpleNamespace(name="r", formula=f, atoms=atoms)
            m.ltls = [spec]
            lassos = violating_lassos(m, spec)
            for fair in ("none", "weak", "strong"):
                res = check_ltl(m, spec, fair, "proc")
                self.assertFalse(res.limited)
                bf = brute_force_violation(m, spec, fair, lassos)
                if bf is not None:
                    found_violations += 1
                    self.assertFalse(res.ok, (fair, f, bf))
                if res.violation is not None:
                    res.violation.fairness = fair
                    validate(m, res.violation, fair, "proc")
        self.assertGreater(found_violations, 30)


def violating_lassos(m, spec, max_cycle=6, cap=4000):
    """Enumerate short simple cycles of the system graph (with a shortest-path prefix) whose word
    falsifies the formula.  Fairness is *not* applied here."""
    from argus.ltl import eval_lasso, nnf
    graph = {}

    def succ(s):
        if s not in graph:
            sc = successors(m, s)
            graph[s] = sc if sc else [(-1, STUTTER, s)]
        return graph[s]

    # BFS tree for prefixes
    parent, order = {m.init: None}, [m.init]
    for s in order:
        for pid, e, t in succ(s):
            if t not in parent:
                parent[t] = (s, pid, e)
                order.append(t)
    phi = nnf(spec.formula, True)

    def prefix(s):
        steps = []
        while parent[s] is not None:
            p, pid, e = parent[s]
            steps.append((pid, e, s))
            s = p
        return steps[::-1]

    out = []
    for a in order:
        pre = prefix(a)
        stack = [(a, [])]
        while stack and len(out) < cap:
            s, path = stack.pop()
            for pid, e, t in succ(s):
                np_ = path + [(pid, e, t)]
                if t == a:
                    steps = pre + np_
                    states = [m.init] + [x[2] for x in steps]
                    vals = []
                    for st in states[:-1]:
                        mask = 0
                        for i, (_, fn) in enumerate(spec.atoms):
                            if fn(st):
                                mask |= 1 << i
                        vals.append(mask)
                    if not eval_lasso(phi, vals, len(pre))[0]:
                        out.append(Violation("ltl", "r", "", Trace(m.init, steps, loop_to=len(pre)), spec))
                elif len(np_) < max_cycle and all(x[2] != t for x in np_[:-1]):
                    stack.append((t, np_))
    return out


def brute_force_violation(m, spec, fair, lassos):
    for v in lassos:
        try:
            validate(m, v, fair, "proc")
            return v
        except ValidationError:
            pass
    return None


if __name__ == "__main__":
    unittest.main()
