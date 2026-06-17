"""Test suite exercising every Resolvent feature. Run: python3 -m unittest -v
(from the project root) or via ./demo.sh."""
import os
import re
import sys
import random
import subprocess
import tempfile
import unittest
import xml.dom.minidom as minidom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolvent.cnf import CNF, DimacsError
from resolvent.solver import Solver
from resolvent.bruteforce import truth_table_sat, dpll_sat
from resolvent import encoders
from resolvent.proof import check_unsat_proof, rup_implied
from resolvent.viz import render_conflict_html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def solve(f):
    s = Solver(f)
    sat = s.solve()
    return sat, (s.model() if sat else None), s


class TestDimacs(unittest.TestCase):
    def test_roundtrip(self):
        f = CNF(4)
        for cl in [[1, -2, 3], [-1, 2], [-3, 4]]:
            f.add_clause(cl)
        g = CNF.parse_dimacs(f.to_dimacs())
        self.assertEqual(f.clauses, g.clauses)
        self.assertEqual(f.nvars, g.nvars)

    def test_no_header_and_multiline(self):
        f = CNF.parse_dimacs("1 2\n3 0\n-1 0\n")
        self.assertEqual(f.clauses, [[1, 2, 3], [-1]])

    def test_tautology_and_dupes(self):
        f = CNF(3)
        f.add_clause([1, -1, 2])     # tautology -> dropped
        f.add_clause([2, 2, -3, -3]) # dupes collapsed
        self.assertEqual(f.clauses, [[2, -3]])

    def test_errors(self):
        with self.assertRaises(DimacsError):
            CNF.parse_dimacs("p cnf 1 1\n1 2 0\n")  # var exceeds declared
        with self.assertRaises(DimacsError):
            CNF.parse_dimacs("p cnf 2 1\nx 0\n")     # non-integer
        with self.assertRaises(DimacsError):
            CNF.parse_dimacs("p oops\n")             # bad header


class TestSolverBasics(unittest.TestCase):
    def test_empty_formula_sat(self):
        sat, model, _ = solve(CNF(0))
        self.assertTrue(sat)

    def test_empty_clause_unsat(self):
        f = CNF(2)
        f.add_clause([1])
        f.clauses.append([])
        self.assertFalse(Solver(f).solve())

    def test_units(self):
        f = CNF(1); f.add_clause([1])
        sat, m, _ = solve(f)
        self.assertTrue(sat); self.assertTrue(m[1])

    def test_contradictory_units(self):
        f = CNF(1); f.add_clause([1]); f.add_clause([-1])
        self.assertFalse(Solver(f).solve())

    def test_known_unsat(self):
        f = CNF(2)
        for cl in [[1, 2], [1, -2], [-1, 2], [-1, -2]]:
            f.add_clause(cl)
        self.assertFalse(Solver(f).solve())

    def test_determinism(self):
        random.seed(11)
        f = CNF(35)
        for _ in range(140):
            vs = random.sample(range(1, 36), 3)
            f.add_clause([v if random.random() < 0.5 else -v for v in vs])
        runs = []
        for _ in range(3):
            s = Solver(f)
            sat = s.solve()
            runs.append((sat, tuple(sorted(s.model().items())), s.stats.conflicts))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])


class TestDifferential(unittest.TestCase):
    def test_vs_truth_table(self):
        rng = random.Random(7)
        for _ in range(1200):
            nv = rng.randint(1, 9)
            nc = rng.randint(1, int(nv * 4.5) + 1)
            f = CNF(nv)
            for _ in range(nc):
                k = rng.randint(1, min(3, nv))
                f.add_clause([(v if rng.random() < 0.5 else -v)
                              for v in (rng.randint(1, nv) for _ in range(k))])
            sat, model, _ = solve(f)
            self.assertEqual(sat, truth_table_sat(f), msg=f"{f.clauses}")
            if sat:
                self.assertTrue(f.is_satisfied_by(model), msg=f"bad model {f.clauses}")

    def test_vs_dpll(self):
        rng = random.Random(123)
        for _ in range(600):
            nv = rng.randint(3, 15)
            nc = rng.randint(nv, int(nv * 4.3))
            f = CNF(nv)
            for _ in range(nc):
                vs = rng.sample(range(1, nv + 1), 3)
                f.add_clause([v if rng.random() < 0.5 else -v for v in vs])
            self.assertEqual(Solver(f).solve(), dpll_sat(f), msg=f"{f.clauses}")


class TestEncoders(unittest.TestCase):
    def test_sudoku(self):
        f, meta = encoders.encode_sudoku(encoders.DEFAULT_SUDOKU)
        s = Solver(f); self.assertTrue(s.solve())
        grid = encoders.decode_sudoku(s.model(), meta)
        self.assertTrue(encoders.is_valid_sudoku(grid))
        # Givens preserved.
        for idx, ch in enumerate(encoders.DEFAULT_SUDOKU):
            if ch not in "0.":
                r, c = divmod(idx, 9)
                self.assertEqual(grid[r][c], int(ch))

    def test_sudoku_invalid_size(self):
        with self.assertRaises(ValueError):
            encoders.encode_sudoku("123")

    def test_queens(self):
        for n in (4, 8, 10):
            f, meta = encoders.encode_queens(n)
            s = Solver(f); self.assertTrue(s.solve())
            pos = encoders.decode_queens(s.model(), meta)
            self.assertTrue(encoders.is_valid_queens(pos))
        # N=2 and N=3 have no solution.
        self.assertFalse(Solver(encoders.encode_queens(2)[0]).solve())
        self.assertFalse(Solver(encoders.encode_queens(3)[0]).solve())

    def test_coloring(self):
        n, edges, k = encoders.NAMED_GRAPHS["petersen"]
        f, meta = encoders.encode_coloring(n, edges, k)
        s = Solver(f); self.assertTrue(s.solve())
        self.assertTrue(encoders.is_valid_coloring(
            encoders.decode_coloring(s.model(), meta), meta))
        f2, _ = encoders.encode_coloring(n, edges, 2)
        self.assertFalse(Solver(f2).solve())  # chromatic number is 3

    def test_php_unsat(self):
        for n in (3, 4, 5):
            f, _ = encoders.encode_php(n)
            self.assertFalse(Solver(f).solve())


class TestProof(unittest.TestCase):
    def test_accepts_real_proof(self):
        for n in (3, 4, 5):
            f, _ = encoders.encode_php(n)
            s = Solver(f, record_proof=True)
            self.assertFalse(s.solve())
            ok, msg = check_unsat_proof(f, s.get_proof())
            self.assertTrue(ok, msg)

    def test_rejects_bogus_proof(self):
        f = CNF(2)
        for cl in [[1, 2], [1, -2], [-1, 2], [-1, -2]]:
            f.add_clause(cl)
        # Jumping straight to the empty clause is not RUP here.
        ok, _ = check_unsat_proof(f, [[]])
        self.assertFalse(ok)

    def test_rup_non_vacuous(self):
        # A clause that is genuinely not implied must be rejected.
        self.assertFalse(rup_implied([[1, 2]], [-1, -2]))
        # A subsumed clause is implied.
        self.assertTrue(rup_implied([[1, 2]], [1, 2]))


class TestViz(unittest.TestCase):
    def test_wellformed_svg(self):
        f, _ = encoders.encode_php(4)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "g.html")
            render_conflict_html(f, out)
            with open(out) as fh:
                html = fh.read()
            m = re.search(r"<svg.*?</svg>", html, re.S)
            self.assertIsNotNone(m)
            minidom.parseString(m.group(0))  # raises on malformed XML
            self.assertIn("1-UIP", html)
            self.assertIn("κ", html)  # conflict node kappa


class TestCLI(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "resolvent", *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_solve_sat(self):
        r = self._run("solve", "examples/sat_simple.cnf")
        self.assertEqual(r.returncode, 10)
        self.assertIn("SATISFIABLE", r.stdout)
        self.assertIn("model verified", r.stdout)

    def test_solve_unsat(self):
        r = self._run("solve", "examples/unsat_simple.cnf")
        self.assertEqual(r.returncode, 20)
        self.assertIn("UNSATISFIABLE", r.stdout)

    def test_decode_sudoku(self):
        r = self._run("decode", "sudoku")
        self.assertEqual(r.returncode, 10)
        self.assertIn("valid completed Sudoku: True", r.stdout)

    def test_verify(self):
        r = self._run("verify", "examples/unsat_simple.cnf")
        self.assertEqual(r.returncode, 20)
        self.assertIn("PROOF VERIFIED", r.stdout)

    def test_missing_file(self):
        r = self._run("solve", "does_not_exist.cnf")
        self.assertEqual(r.returncode, 2)

    def test_bad_param(self):
        r = self._run("decode", "queens", "abc")
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
