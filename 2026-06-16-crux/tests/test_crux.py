"""Crux test suite — exercises every feature and guards the review fixes.

Run: python3 -m unittest discover -s tests   (from the project root)
"""

import json
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crux import CNF, Solver, parse_dimacs, brute_is_sat, brute_count, DimacsError
from crux.solver import luby
from crux.counter import model_count
from crux.proof import check_proof
from crux.viz import build_visualizer
from crux import encoders as enc


def rand_cnf(rng, nv, nc, maxk=3):
    c = CNF()
    for _ in range(nc):
        k = rng.randint(1, min(maxk, nv))
        lits, used = [], set()
        while len(lits) < k:
            v = rng.randint(1, nv)
            if v in used:
                continue
            used.add(v)
            lits.append(v if rng.random() < 0.5 else -v)
        c.add_clause(lits)
    c.nvars = nv
    return c


class TestDimacs(unittest.TestCase):
    def test_parse_and_roundtrip(self):
        txt = "c hi\np cnf 3 2\n1 -2 0\n2 3 0\n"
        cnf = parse_dimacs(txt)
        self.assertEqual(cnf.nvars, 3)
        self.assertEqual([list(c) for c in cnf.clauses], [[1, -2], [2, 3]])
        again = parse_dimacs(cnf.to_dimacs())
        self.assertEqual(again.clauses, cnf.clauses)

    def test_multiline_and_no_trailing_zero(self):
        cnf = parse_dimacs("p cnf 4 2\n1 2\n3 0\n-4")
        self.assertEqual([list(c) for c in cnf.clauses], [[1, 2, 3], [-4]])

    def test_percent_trailer(self):
        cnf = parse_dimacs("p cnf 2 1\n1 2 0\n%\n0\n")
        self.assertEqual([list(c) for c in cnf.clauses], [[1, 2]])

    def test_bad_header_raises(self):
        with self.assertRaises(DimacsError):
            parse_dimacs("p cnf x y\n1 0\n")

    def test_tautology_dropped(self):
        c = CNF()
        c.add_clause([1, -1, 2])
        self.assertEqual(c.nclauses, 0)  # tautology not stored


class TestSolverCore(unittest.TestCase):
    def test_simple_sat(self):
        c = CNF()
        for cl in ([1, 2], [-1, 2], [-2, 3]):
            c.add_clause(cl)
        r = Solver(c).solve()
        self.assertTrue(r.sat)
        self.assertTrue(c.is_satisfied_by(r.model))

    def test_unit_conflict_unsat(self):
        c = CNF()
        c.add_clause([1])
        c.add_clause([-1])
        self.assertFalse(Solver(c).solve().sat)

    def test_empty_formula_sat(self):
        self.assertTrue(Solver(CNF(nvars=3)).solve().sat)

    def test_empty_clause_unsat(self):
        c = CNF()
        c.clauses.append([])
        c.nvars = 2
        self.assertFalse(Solver(c).solve().sat)

    def test_status_strings(self):
        c = CNF(); c.add_clause([1])
        self.assertEqual(Solver(c).solve().status, "SAT")
        u = CNF(); u.add_clause([1]); u.add_clause([-1])
        self.assertEqual(Solver(u).solve().status, "UNSAT")

    def test_luby_sequence(self):
        seq = [luby(i) for i in range(1, 16)]
        self.assertEqual(seq, [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8])


class TestDifferential(unittest.TestCase):
    def test_fuzz_vs_brute(self):
        rng = random.Random(20260616)
        sat = unsat = 0
        for t in range(2500):
            nv = rng.randint(1, 8)
            c = rand_cnf(rng, nv, rng.randint(0, nv * 4))
            r = Solver(c.copy(), restart_base=1 + (t % 50)).solve()
            b = brute_is_sat(c)
            self.assertEqual(r.sat, b, msg=f"trial {t}: {[list(x) for x in c.clauses]}")
            if r.sat:
                sat += 1
                self.assertTrue(c.is_satisfied_by(r.model))
            else:
                unsat += 1
        self.assertGreater(sat, 100)
        self.assertGreater(unsat, 100)


class TestAssumptions(unittest.TestCase):
    def mk(self):
        c = CNF()
        for cl in ([1, 2], [-1, 3], [-2, -3]):
            c.add_clause(cl)
        return c

    def test_assumptions(self):
        self.assertTrue(Solver(self.mk()).solve([1]).sat)
        self.assertFalse(Solver(self.mk()).solve([1, -3]).sat)
        self.assertFalse(Solver(self.mk()).solve([2, 3]).sat)
        r = Solver(self.mk()).solve([1])
        self.assertIs(r.model[1], True)


class TestEncoders(unittest.TestCase):
    def test_sudoku(self):
        grid = [[int(ch) for ch in row] for row in
                ("530070000 600195000 098000060 800060003 400803001 "
                 "700020006 060000280 000419005 000080079").split()]
        cnf, meta = enc.sudoku_encode(grid)
        r = Solver(cnf).solve()
        self.assertTrue(r.sat)
        sol = enc.sudoku_decode(r.model, meta)
        for i in range(9):
            self.assertEqual(sorted(sol[i]), list(range(1, 10)))
            self.assertEqual(sorted(sol[r2][i] for r2 in range(9)), list(range(1, 10)))
        for br in (0, 3, 6):
            for bc in (0, 3, 6):
                box = [sol[br + i][bc + j] for i in range(3) for j in range(3)]
                self.assertEqual(sorted(box), list(range(1, 10)))
        for i in range(9):
            for j in range(9):
                if grid[i][j]:
                    self.assertEqual(sol[i][j], grid[i][j])

    def test_queens(self):
        for n in (4, 6, 8, 10):
            cnf, meta = enc.nqueens_encode(n)
            r = Solver(cnf).solve()
            self.assertTrue(r.sat)
            cols = enc.nqueens_decode(r.model, meta)
            for i in range(n):
                for j in range(i + 1, n):
                    self.assertNotEqual(cols[i], cols[j])
                    self.assertNotEqual(abs(cols[i] - cols[j]), abs(i - j))

    def test_coloring(self):
        edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]
        self.assertTrue(Solver(enc.graph_coloring_encode(5, edges, 3)[0]).solve().sat)
        self.assertFalse(Solver(enc.graph_coloring_encode(5, edges, 2)[0]).solve().sat)

    def test_pigeonhole(self):
        self.assertTrue(Solver(enc.pigeonhole_encode(4, 4)[0]).solve().sat)
        for (m, n) in [(3, 2), (4, 3), (5, 4)]:
            self.assertFalse(Solver(enc.pigeonhole_encode(m, n)[0]).solve().sat)


class TestModelCount(unittest.TestCase):
    def test_count_vs_brute(self):
        rng = random.Random(99)
        for _ in range(300):
            nv = rng.randint(1, 7)
            c = rand_cnf(rng, nv, rng.randint(0, nv * 3))
            self.assertEqual(model_count(c), brute_count(c))

    def test_known_counts(self):
        # 3 independent variables, no clauses -> 2^3 models
        c = CNF(nvars=3)
        self.assertEqual(model_count(c), 8)
        # x1 alone -> half of 2 = 1
        c = CNF(); c.add_clause([1]); c.nvars = 1
        self.assertEqual(model_count(c), 1)


class TestProof(unittest.TestCase):
    def test_pigeonhole_proofs(self):
        for (m, n) in [(2, 1), (3, 2), (4, 3), (5, 4)]:
            cnf = enc.pigeonhole_encode(m, n)[0]
            r = Solver(cnf.copy(), record_proof=True).solve()
            self.assertFalse(r.sat)
            ok, info = check_proof(cnf, r.proof)
            self.assertTrue(ok, msg=f"PHP {m}->{n} proof invalid: {info}")

    def test_random_unsat_proofs(self):
        rng = random.Random(7)
        checked = 0
        for _ in range(200):
            nv = rng.randint(1, 5)
            c = rand_cnf(rng, nv, rng.randint(nv, nv * 5))
            r = Solver(c.copy(), record_proof=True).solve()
            if not r.sat:
                ok, info = check_proof(c, r.proof)
                self.assertTrue(ok, msg=f"proof invalid: {info}")
                checked += 1
        self.assertGreater(checked, 20)

    def test_bogus_proof_rejected(self):
        # A *satisfiable* formula: no UNSAT certificate can be valid for it.
        cnf = CNF(); cnf.add_clause([1, 2]); cnf.add_clause([-1, 2]); cnf.nvars = 2
        # claiming the empty clause must be rejected (not RUP-derivable)
        self.assertFalse(check_proof(cnf, [["a"]])[0])
        # claiming a non-implied clause (¬x2, but x2 is forced true) must fail
        self.assertFalse(check_proof(cnf, [["a", -2], ["a"]])[0])


class TestReviewRegressions(unittest.TestCase):
    def test_heap_bounded(self):
        """F1: the VSIDS order heap must stay O(nvars), not blow up."""
        s = Solver(enc.pigeonhole_encode(8, 7)[0])
        s.solve()
        self.assertLess(len(s.order), 40 * (s.nvars + 1) + 2048)

    def test_conflict_budget(self):
        """F3: max_conflicts returns UNKNOWN rather than looping."""
        r = Solver(enc.pigeonhole_encode(9, 8)[0]).solve(max_conflicts=20)
        self.assertIsNone(r.sat)
        self.assertEqual(r.status, "UNKNOWN")
        self.assertLessEqual(r.stats.conflicts, 21)

    def test_no_rng_seed_param(self):
        """F2: the dead rng_seed parameter was removed."""
        with self.assertRaises(TypeError):
            Solver(rng_seed=1)


class TestVisualizer(unittest.TestCase):
    def test_build_and_embed(self):
        cnf = enc.pigeonhole_encode(5, 4)[0]
        html = build_visualizer(cnf, title="t")
        self.assertIn("<svg", html)
        m = re.search(r"const DATA = (.*?);\nconst SVGNS", html, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertEqual(data["status"], "UNSAT")
        self.assertGreater(len(data["snaps"]), 0)
        snap = data["snaps"][0]
        for key in ("conflict", "trail", "learned", "uip", "btlevel"):
            self.assertIn(key, snap)

    def test_zero_conflict_instance(self):
        # a formula solved by pure propagation -> no conflict snapshots
        c = CNF(); c.add_clause([1]); c.add_clause([2])
        html = build_visualizer(c)
        m = re.search(r"const DATA = (.*?);\nconst SVGNS", html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(data["status"], "SAT")
        self.assertEqual(len(data["snaps"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
