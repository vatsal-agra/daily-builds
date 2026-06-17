"""Full test suite for Resolvent. Run: python3 -m unittest -v (from project root)."""
import itertools
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolvent.cnf import CNF
from resolvent.solver import Solver, solve_cnf, luby
from resolvent.model import Model, AND, OR, NOT, XOR, IFF, IMPLIES
from resolvent.proof import (check_proof, is_rup, brute_force_sat,
                             count_models_dpll, count_models_bruteforce)
from resolvent.puzzles import sudoku, nqueens, coloring, pigeonhole
from resolvent import viz


def brute(cnf):
    return brute_force_sat(cnf)


class TestCNF(unittest.TestCase):
    def test_dimacs_roundtrip(self):
        text = "c hi\np cnf 3 2\n1 -2 0\n2 3 0\n"
        f = CNF.from_dimacs(text)
        self.assertEqual(f.nvars, 3)
        self.assertEqual(f.clauses, [[1, -2], [2, 3]])
        f2 = CNF.from_dimacs(f.to_dimacs())
        self.assertEqual(f2.clauses, f.clauses)

    def test_missing_trailing_zero(self):
        f = CNF.from_dimacs("p cnf 2 1\n1 2")
        self.assertEqual(f.clauses, [[1, 2]])

    def test_model_check(self):
        f = CNF(2); f.add_clause([1, 2]); f.add_clause([-1])
        self.assertTrue(f.is_satisfied_by({1: False, 2: True}))
        self.assertFalse(f.is_satisfied_by({1: True, 2: True}))


class TestLuby(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual([luby(i) for i in range(1, 16)],
                         [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8])


class TestSolverCore(unittest.TestCase):
    def test_simple_sat(self):
        f = CNF(); f.add_clause([1, 2]); f.add_clause([-1, 2]); f.add_clause([-2, 3])
        res, m, _ = solve_cnf(f)
        self.assertTrue(res)
        self.assertTrue(f.is_satisfied_by(m))

    def test_simple_unsat(self):
        f = CNF()
        for c in [[1, 2], [1, -2], [-1, 2], [-1, -2]]:
            f.add_clause(c)
        res, _, _ = solve_cnf(f)
        self.assertIs(res, False)

    def test_empty_formula_sat(self):
        self.assertIs(solve_cnf(CNF(0))[0], True)

    def test_empty_clause_unsat(self):
        f = CNF(2); f.add_clause([1]); f.add_clause([])
        self.assertIs(solve_cnf(f)[0], False)

    def test_tautology_and_dups(self):
        f = CNF(2); f.add_clause([1, -1]); f.add_clause([2, 2])
        res, m, _ = solve_cnf(f)
        self.assertTrue(res)
        self.assertTrue(m[2])

    def test_free_vars_assigned(self):
        f = CNF(6); f.add_clause([1])
        res, m, _ = solve_cnf(f)
        self.assertTrue(res)
        self.assertEqual(len(m), 6)

    def test_differential_vs_bruteforce(self):
        rng = random.Random(1234)
        for _ in range(500):
            n = rng.randint(1, 9)
            f = CNF(n)
            for _ in range(rng.randint(0, 28)):
                k = rng.randint(1, 3)
                f.add_clause([(v if rng.random() < .5 else -v)
                              for v in rng.sample(range(1, n + 1), min(k, n))])
            expect = brute(f)
            for kw in (dict(), dict(restarts=False), dict(reduce_db=False)):
                res, m, _ = solve_cnf(f, **kw)
                self.assertEqual(res is True, expect, msg=str(f.clauses))
                if res is True:
                    self.assertTrue(f.is_satisfied_by(m))


class TestProof(unittest.TestCase):
    def test_rup_basic(self):
        self.assertTrue(is_rup([1], [[1]]))
        self.assertFalse(is_rup([1], [[1, 2, 3]]))

    def test_unsat_proofs_verify(self):
        rng = random.Random(77)
        checked = 0
        for _ in range(400):
            n = rng.randint(1, 7)
            f = CNF(n)
            for _ in range(rng.randint(3, 24)):
                k = rng.randint(1, 3)
                f.add_clause([(v if rng.random() < .5 else -v)
                              for v in rng.sample(range(1, n + 1), min(k, n))])
            if brute(f):
                continue
            s = Solver(f, record_proof=True)
            self.assertIs(s.solve(), False)
            ok, msg = check_proof(f, s.proof)
            self.assertTrue(ok, msg=msg)
            checked += 1
        self.assertGreater(checked, 50)

    def test_proof_rejects_invalid(self):
        f = CNF(3); f.add_clause([1, 2, 3])
        ok, _ = check_proof(f, [("a", [])])
        self.assertFalse(ok)
        f2 = CNF(2); f2.add_clause([1, 2]); f2.add_clause([-1, 2]); f2.add_clause([-2, 3])
        ok2, _ = check_proof(f2, [("a", [-3]), ("a", [])])
        self.assertFalse(ok2)

    def test_php_unsat_with_reduce(self):
        puz = pigeonhole.Pigeonhole(7, 6)
        s = Solver(puz.model.cnf, record_proof=True)
        self.assertIs(s.solve(), False)
        self.assertGreater(s.stats.removed_clauses, 0)  # reduceDB exercised
        ok, msg = check_proof(puz.model.cnf, s.proof)
        self.assertTrue(ok, msg=msg)

    def test_model_counter(self):
        rng = random.Random(9)
        for _ in range(300):
            n = rng.randint(1, 7)
            f = CNF(n)
            for _ in range(rng.randint(0, 14)):
                k = rng.randint(1, 3)
                f.add_clause([(v if rng.random() < .5 else -v)
                              for v in rng.sample(range(1, n + 1), min(k, n))])
            self.assertEqual(count_models_dpll(f), count_models_bruteforce(f))


class TestModeling(unittest.TestCase):
    def _gate(self, builder, ref):
        for av, bv in itertools.product((0, 1), repeat=2):
            md = Model(); a = md.new_var(); b = md.new_var()
            md.cnf.add_clause([a if av else -a]); md.cnf.add_clause([b if bv else -b])
            z = md.encode(builder(a, b)); md.cnf.add_clause([z])
            res, _, _ = solve_cnf(md.cnf)
            self.assertEqual(res is True, bool(ref(av, bv)))

    def test_gates(self):
        self._gate(lambda a, b: XOR(a, b), lambda x, y: x ^ y)
        self._gate(lambda a, b: AND(a, b), lambda x, y: x & y)
        self._gate(lambda a, b: OR(a, b), lambda x, y: x | y)
        self._gate(lambda a, b: IFF(a, b), lambda x, y: int(x == y))
        self._gate(lambda a, b: IMPLIES(a, b), lambda x, y: int((not x) or y))
        self._gate(lambda a, b: NOT(AND(a, b)), lambda x, y: 1 - (x & y))

    def _card(self, setup, pred, n):
        for assign in itertools.product((0, 1), repeat=n):
            md = Model(); lits = [md.new_var() for _ in range(n)]
            setup(md, lits)
            for i, v in enumerate(assign):
                md.cnf.add_clause([lits[i] if v else -lits[i]])
            res, _, _ = solve_cnf(md.cnf)
            self.assertEqual(res is True, pred(assign), msg=f"n={n} a={assign}")

    def test_cardinality(self):
        for n in range(1, 7):
            self._card(lambda md, l: md.at_most_one(l), lambda a: sum(a) <= 1, n)
            self._card(lambda md, l: md.exactly_one(l), lambda a: sum(a) == 1, n)
            for k in range(0, n + 1):
                self._card(lambda md, l, k=k: md.at_most_k(l, k),
                           lambda a, k=k: sum(a) <= k, n)
                self._card(lambda md, l, k=k: md.at_least_k(l, k),
                           lambda a, k=k: sum(a) >= k, n)
                self._card(lambda md, l, k=k: md.exactly_k(l, k),
                           lambda a, k=k: sum(a) == k, n)


class TestSudoku(unittest.TestCase):
    def test_hardest_sudoku(self):
        grid = ("8........" "..36....." ".7..9.2.."
                ".5...7..." "....457.." "...1...3."
                "..1....68" "..85...1." ".9....4..")
        sol = sudoku.Sudoku(sudoku.parse_grid(grid)).solve()
        self.assertIsNotNone(sol)
        self.assertTrue(sudoku.is_valid_solution(sol))

    def test_givens_respected(self):
        grid = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
        S = sudoku.Sudoku(sudoku.parse_grid(grid))
        sol = S.solve()
        for r in range(9):
            for c in range(9):
                if S.given[r][c]:
                    self.assertEqual(sol[r][c], S.given[r][c])

    def test_contradictory_unsat(self):
        rows = [[0] * 9 for _ in range(9)]
        rows[0][0] = 1; rows[0][1] = 1  # two 1s in a row
        self.assertIsNone(sudoku.Sudoku(rows).solve())

    def test_4x4(self):
        sol = sudoku.Sudoku([[1, 0, 0, 0]] + [[0] * 4 for _ in range(3)]).solve()
        self.assertTrue(sudoku.is_valid_solution(sol))

    def test_parse_forms(self):
        compact = "1234341221434321"
        block = "12\n34\n"
        spaced = "1 2\n3 4\n"
        self.assertEqual(len(sudoku.parse_grid(block)), 2)
        self.assertEqual(sudoku.parse_grid(spaced)[1], [3, 4])
        self.assertEqual(len(sudoku.parse_grid(compact)), 4)


class TestQueens(unittest.TestCase):
    def test_solutions(self):
        for n in (1, 4, 6, 8, 10):
            cols = nqueens.NQueens(n).solve()
            self.assertTrue(nqueens.is_valid(cols), msg=f"n={n}")

    def test_unsat_small(self):
        self.assertIsNone(nqueens.NQueens(2).solve())
        self.assertIsNone(nqueens.NQueens(3).solve())


class TestColoring(unittest.TestCase):
    def setUp(self):
        self.petersen = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0), (0, 5),
                         (1, 6), (2, 7), (3, 8), (4, 9), (5, 7), (7, 9),
                         (9, 6), (6, 8), (8, 5)]

    def test_petersen_3colorable(self):
        col = coloring.Coloring(10, self.petersen, 3).solve()
        self.assertTrue(coloring.is_valid(col, self.petersen, 3))

    def test_petersen_not_2colorable(self):
        self.assertIsNone(coloring.Coloring(10, self.petersen, 2).solve())

    def test_k4(self):
        k4 = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        self.assertIsNone(coloring.Coloring(4, k4, 3).solve())
        self.assertTrue(coloring.is_valid(coloring.Coloring(4, k4, 4).solve(), k4, 4))

    def test_parse_graph(self):
        n, edges = coloring.parse_graph("3\n0 1\n1 2\n")
        self.assertEqual(n, 3)
        self.assertEqual(edges, [(0, 1), (1, 2)])


class TestPigeonhole(unittest.TestCase):
    def test_sat_when_fits(self):
        place = pigeonhole.Pigeonhole(5, 5).solve()
        self.assertIsNotNone(place)
        self.assertEqual(len(set(place)), 5)

    def test_unsat_classic(self):
        for m in range(2, 7):
            self.assertIsNone(pigeonhole.Pigeonhole(m, m - 1).solve(), msg=f"PHP({m},{m-1})")


class TestViz(unittest.TestCase):
    def test_html_payload(self):
        cnf = pigeonhole.Pigeonhole(4, 3).model.cnf
        html = viz.render_report(cnf, title="PHP(4,3)")
        self.assertIn("Resolvent", html)
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertNotIn("__TITLE__", html)
        payload = html.split("const DATA = ", 1)[1].split(";\nconst SVGNS", 1)[0]
        data = json.loads(payload)
        self.assertEqual(data["verdict"], "UNSATISFIABLE")
        self.assertGreater(len(data["conflicts"]), 0)
        c = data["conflicts"][0]
        self.assertGreater(len(c["nodes"]), 0)
        self.assertGreater(len(c["edges"]), 0)

    def test_sat_report(self):
        cnf = nqueens.NQueens(6).model.cnf
        html = viz.render_report(cnf, title="6-queens")
        self.assertIn("SATISFIABLE", html)


class TestCLI(unittest.TestCase):
    def test_demo(self):
        from resolvent import cli
        rc = cli.main(["demo"])
        self.assertEqual(rc, 0)

    def test_gen_and_solve(self, ):
        from resolvent import cli
        import tempfile
        path = tempfile.mktemp(suffix=".cnf")
        cli.main(["gen", "--vars", "20", "--ratio", "3.0", "--seed", "2", "--out", path])
        rc = cli.main(["solve", path])
        self.assertIn(rc, (10, 20))


if __name__ == "__main__":
    unittest.main()
