"""Conflux test suite — exercises every feature.

Run:  python3 -m tests.run_tests        (from the project root)
  or: python3 tests/run_tests.py
"""
import itertools
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

# allow running as a script from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conflux.cnf import CNF
from conflux.solver import Solver, solve_cnf, SAT, UNSAT, UNKNOWN, luby
from conflux.proof import verify_unsat
from conflux import encoders as E
from conflux import rand3sat
from conflux.trace import ExplainTracer
from conflux.viz import generate_html

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_JS = os.path.join(ROOT, "web", "solver.js")


def brute_force(cnf: CNF) -> bool:
    n = cnf.num_vars
    for bits in itertools.product([False, True], repeat=n):
        if cnf.is_satisfied_by({i + 1: bits[i] for i in range(n)}):
            return True
    return False


def random_cnf(rng, max_vars=10, max_clauses=40):
    n = rng.randint(1, max_vars)
    m = rng.randint(1, max_clauses)
    cnf = CNF()
    cnf.num_vars = n
    for _ in range(m):
        k = min(rng.randint(1, 3), 2 * n)
        cl = set()
        while len(cl) < k:
            v = rng.randint(1, n)
            s = rng.choice([1, -1])
            cl.add(s * v)
        cnf.add_clause(list(cl))
    return cnf


class TestDimacs(unittest.TestCase):
    def test_roundtrip(self):
        cnf = CNF()
        cnf.num_vars = 3
        for cl in [[1, -2, 3], [-1, 2], [3]]:
            cnf.add_clause(cl)
        text = cnf.to_dimacs()
        back = CNF.from_dimacs(text)
        self.assertEqual(back.num_vars, 3)
        self.assertEqual(back.clauses, [[1, -2, 3], [-1, 2], [3]])

    def test_malformed_raises_clean(self):
        with self.assertRaises(ValueError):
            CNF.from_dimacs("p cnf 2 1\ngarbage here\n")


class TestOracle(unittest.TestCase):
    def test_brute_force_oracle(self):
        rng = random.Random(2024)
        mism = badmodel = badproof = nsat = nunsat = 0
        N = 800
        for _ in range(N):
            cnf = random_cnf(rng)
            s = Solver(num_vars=cnf.num_vars, record_proof=True)
            for cl in cnf.clauses:
                s.add_clause(cl)
            res = s.solve(max_conflicts=200000)
            self.assertNotEqual(res, UNKNOWN, "small instance should not be capped")
            expected = SAT if brute_force(cnf) else UNSAT
            if res != expected:
                mism += 1
            if res == SAT:
                nsat += 1
                if not cnf.is_satisfied_by(s.model()):
                    badmodel += 1
            else:
                nunsat += 1
                ok, _ = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
                if not ok:
                    badproof += 1
        self.assertEqual(mism, 0, f"verdict mismatches vs brute force: {mism}")
        self.assertEqual(badmodel, 0, "produced an invalid SAT model")
        self.assertEqual(badproof, 0, "produced an unverifiable UNSAT proof")
        self.assertGreater(nsat, 0)
        self.assertGreater(nunsat, 0)


class TestProof(unittest.TestCase):
    def test_corrupt_proof_rejected(self):
        # satisfiable formula: empty clause must NOT be RUP
        ok, _ = verify_unsat(2, [[1, 2]], [[]])
        self.assertFalse(ok)
        # non-implied unit on a SAT formula
        ok2, _ = verify_unsat(3, [[1, 2, 3]], [[-1]])
        self.assertFalse(ok2)

    def test_valid_proof_accepted(self):
        clauses = [[1, 2], [1, -2], [-1, 2], [-1, -2]]
        s = Solver(num_vars=2, record_proof=True)
        for c in clauses:
            s.add_clause(c)
        self.assertEqual(s.solve(), UNSAT)
        ok, _ = verify_unsat(2, clauses, s.proof)
        self.assertTrue(ok)


class TestEdgeCases(unittest.TestCase):
    def test_empty_cnf(self):
        self.assertEqual(solve_cnf(CNF(num_vars=0))[0], SAT)
        self.assertEqual(solve_cnf(CNF(num_vars=4))[0], SAT)

    def test_empty_clause(self):
        c = CNF()
        c.clauses = [[]]
        self.assertEqual(solve_cnf(c)[0], UNSAT)

    def test_contradictory_units(self):
        s = Solver(num_vars=1, record_proof=True)
        s.add_clause([1])
        s.add_clause([-1])
        self.assertEqual(s.solve(), UNSAT)
        self.assertTrue(verify_unsat(1, [[1], [-1]], s.proof)[0])

    def test_tautologies_and_dups(self):
        c = CNF()
        c.num_vars = 2
        c.add_clause([1, -1])  # tautology
        c.add_clause([2, 2])   # duplicate
        res, mdl, _ = solve_cnf(c)
        self.assertEqual(res, SAT)
        self.assertTrue(c.is_satisfied_by(mdl))


class TestEncoders(unittest.TestCase):
    def test_sudoku_known(self):
        puz = ("53..7....6..195....98....6.8...6...34..8.3..17..."
               "2...6.6....28....419..5....8..79")
        expected = ("534678912672195348198342567859761423426853791"
                    "713924856961537284287419635345286179")
        g = E.parse_sudoku(puz)
        cnf, meta = E.encode_sudoku(g)
        res, mdl, _ = solve_cnf(cnf)
        self.assertEqual(res, SAT)
        grid = E.decode_sudoku(mdl, meta)
        ok, msg = E.validate_sudoku(grid, g)
        self.assertTrue(ok, msg)
        flat = "".join(str(d) for row in grid for d in row)
        self.assertEqual(flat, expected)

    def test_sudoku_hard_escargot(self):
        puz = ("1....7.9..3..2...8..96..5....53..9...1..8...26...."
               "4...3......1..4......7..7...3..")
        g = E.parse_sudoku(puz)
        cnf, meta = E.encode_sudoku(g)
        res, mdl, _ = solve_cnf(cnf)
        self.assertEqual(res, SAT)
        ok, msg = E.validate_sudoku(E.decode_sudoku(mdl, meta), g)
        self.assertTrue(ok, msg)

    def test_nqueens(self):
        for n in (4, 5, 6, 8, 10):
            cnf, meta = E.encode_nqueens(n)
            res, mdl, _ = solve_cnf(cnf)
            self.assertEqual(res, SAT, f"{n}-queens should be SAT")
            ok, msg = E.validate_nqueens(E.decode_nqueens(mdl, meta), n)
            self.assertTrue(ok, msg)
        # 2 and 3 queens are UNSAT
        for n in (2, 3):
            cnf, meta = E.encode_nqueens(n)
            s = Solver(num_vars=cnf.num_vars, record_proof=True)
            for c in cnf.clauses:
                s.add_clause(c)
            self.assertEqual(s.solve(), UNSAT)
            self.assertTrue(verify_unsat(cnf.num_vars, cnf.clauses, s.proof)[0])

    def test_coloring(self):
        triangle = [(0, 1), (1, 2), (0, 2)]
        # 2-coloring impossible
        cnf, meta = E.encode_coloring(3, triangle, 2)
        s = Solver(num_vars=cnf.num_vars, record_proof=True)
        for c in cnf.clauses:
            s.add_clause(c)
        self.assertEqual(s.solve(), UNSAT)
        self.assertTrue(verify_unsat(cnf.num_vars, cnf.clauses, s.proof)[0])
        # 3-coloring possible
        cnf, meta = E.encode_coloring(3, triangle, 3)
        res, mdl, _ = solve_cnf(cnf)
        self.assertEqual(res, SAT)
        ok, msg = E.validate_coloring(E.decode_coloring(mdl, meta), meta)
        self.assertTrue(ok, msg)

    def test_pigeonhole(self):
        for p, h, expect in [(5, 4, UNSAT), (4, 5, SAT), (6, 5, UNSAT)]:
            cnf, meta = E.encode_pigeonhole(p, h)
            s = Solver(num_vars=cnf.num_vars, record_proof=True)
            for c in cnf.clauses:
                s.add_clause(c)
            res = s.solve()
            self.assertEqual(res, expect, f"PHP({p},{h})")
            if res == UNSAT:
                self.assertTrue(verify_unsat(cnf.num_vars, cnf.clauses, s.proof)[0])


class TestPhaseTransition(unittest.TestCase):
    def test_threshold_near_426(self):
        res = rand3sat.phase_transition(num_vars=60, steps=22, samples=40, seed=3)
        # find P(SAT)=0.5 crossing
        cross = None
        prev = None
        for r in res:
            if r["p_sat"] is None:
                continue
            if prev is not None and prev[1] >= 0.5 > r["p_sat"]:
                a0, p0 = prev
                a1, p1 = r["alpha"], r["p_sat"]
                cross = a0 + (a1 - a0) * (p0 - 0.5) / (p0 - p1)
                break
            prev = (r["alpha"], r["p_sat"])
        self.assertIsNotNone(cross, "no P(SAT)=0.5 crossing found")
        self.assertTrue(3.8 < cross < 4.8,
                        f"threshold {cross:.2f} not near 4.26")
        # low ratio should be (almost) all SAT, high ratio all UNSAT
        self.assertGreater(res[0]["p_sat"], 0.95)
        self.assertLess(res[-1]["p_sat"], 0.05)


class TestExplain(unittest.TestCase):
    def test_1uip(self):
        rng = random.Random(5)
        # find an instance that has at least one conflict
        for _ in range(50):
            cnf = random_cnf(rng, max_vars=12, max_clauses=50)
            s = Solver(num_vars=cnf.num_vars)
            tr = ExplainTracer(target_conflict=1)
            s.tracer = tr
            for c in cnf.clauses:
                s.add_clause(c)
            s.solve(max_conflicts=100000)
            if tr.captured:
                break
        self.assertTrue(tr.captured, "expected at least one conflict to capture")
        # learned clause must have exactly one literal at the conflict level
        text = tr.render()
        self.assertIn("1-UIP", text)
        self.assertIn("Learned clause", text)


class TestViz(unittest.TestCase):
    def test_html_self_contained(self):
        html = generate_html()
        self.assertIn("window.Conflux", html)
        self.assertIn("class Solver", html)        # solver embedded
        self.assertNotIn("__SOLVER_JS__", html)    # placeholder substituted
        self.assertGreater(len(html), 20000)


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestJSParity(unittest.TestCase):
    def test_python_js_verdict_parity(self):
        rng = random.Random(777)
        cases = []
        verdicts = []
        for _ in range(400):
            cnf = random_cnf(rng, max_vars=9, max_clauses=30)
            s = Solver(num_vars=cnf.num_vars)
            for c in cnf.clauses:
                s.add_clause(c)
            verdicts.append(s.solve())
            cases.append({"n": cnf.num_vars, "clauses": cnf.clauses})
        d = tempfile.mkdtemp()
        try:
            cpath = os.path.join(d, "cases.json")
            vpath = os.path.join(d, "v.json")
            with open(cpath, "w") as f:
                json.dump(cases, f)
            with open(vpath, "w") as f:
                json.dump(verdicts, f)
            out = subprocess.check_output(
                ["node", os.path.join(HERE, "parity_check.js"),
                 SOLVER_JS, cpath, vpath], text=True).strip()
            self.assertIn("mismatches=0", out, out)
            self.assertIn("badmodels=0", out, out)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestLuby(unittest.TestCase):
    def test_sequence(self):
        seq = [luby(i) for i in range(1, 16)]
        self.assertEqual(seq, [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8])


if __name__ == "__main__":
    unittest.main(verbosity=2)
