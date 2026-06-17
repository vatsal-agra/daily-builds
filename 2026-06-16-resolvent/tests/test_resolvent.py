"""Test suite for Resolvent — exercises every feature, with the brute-force
oracle as ground truth. Run: python3 -m unittest discover -s tests -v"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolvent.cnf import CNF, parse_dimacs, DimacsError
from resolvent.solver import Solver, luby
from resolvent.oracle import brute_force, count_models
from resolvent.generate import random_ksat, random_at_ratio
from resolvent import encoders
from resolvent import proof as proofmod
from resolvent import viz as vizmod


class TestDimacs(unittest.TestCase):
    def test_roundtrip(self):
        c = CNF(4, [[1, -2, 3], [-1, 4], [2]])
        c2 = parse_dimacs(c.to_dimacs())
        self.assertEqual(c2.nvars, c.nvars)
        self.assertEqual(c2.clauses, c.clauses)

    def test_comments_and_split_clauses(self):
        txt = "c hello\n\np cnf 3 2\n1 2\n-3 0\n2 -1 0\n%\n0\n"
        c = parse_dimacs(txt)
        self.assertEqual(c.clauses, [[1, 2, -3], [2, -1]])

    def test_empty_clause(self):
        c = parse_dimacs("p cnf 2 1\n0\n")
        self.assertEqual(c.clauses, [[]])

    def test_errors(self):
        with self.assertRaises(DimacsError):
            parse_dimacs("1 2 0\n")  # data before header
        with self.assertRaises(DimacsError):
            parse_dimacs("p cnf 3 1\n1 x 0\n")  # bad token
        with self.assertRaises(DimacsError):
            parse_dimacs("p cnf 2 1\n1 2\n")  # missing terminating 0
        with self.assertRaises(DimacsError):
            parse_dimacs("p wat 1 1\n")  # bad header


class TestLuby(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual([luby(i) for i in range(1, 16)],
                         [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8])


class TestSolverBasics(unittest.TestCase):
    def test_simple_sat(self):
        c = CNF(3, [[1, 2], [-1, 2], [-2, 3]])
        s = Solver(c)
        self.assertTrue(s.solve())
        self.assertTrue(c.is_satisfied_by(s.model()))

    def test_simple_unsat(self):
        self.assertFalse(Solver(CNF(1, [[1], [-1]])).solve())

    def test_empty_clause_unsat(self):
        self.assertFalse(Solver(CNF(2, [[]])).solve())

    def test_empty_formula_sat(self):
        self.assertTrue(Solver(CNF(0, [])).solve())

    def test_tautology_and_dups(self):
        c = CNF(3, [[1, -1], [2, 2, 3]])
        s = Solver(c)
        self.assertTrue(s.solve())
        self.assertTrue(c.is_satisfied_by(s.model()))


class TestDifferential(unittest.TestCase):
    """The headline correctness gate: CDCL must match brute force, always."""

    def test_fuzz_vs_oracle(self):
        mismatches = 0
        bad_models = 0
        sat = 0
        N = 1500
        for i in range(N):
            nv = (i % 10) + 4               # 4..13 vars
            ratio = 3.0 + (i % 300) / 100.0  # 3.0 .. 6.0
            c = random_at_ratio(nv, ratio, k=3, seed=i * 2654435761 % 100000)
            exp, _ = brute_force(c)
            s = Solver(c, seed=i)
            got = s.solve()
            if got != exp:
                mismatches += 1
            elif got:
                sat += 1
                if not c.is_satisfied_by(s.model()):
                    bad_models += 1
        self.assertEqual(mismatches, 0, "verdict mismatches vs oracle")
        self.assertEqual(bad_models, 0, "produced an invalid model")
        self.assertGreater(sat, 0)
        self.assertLess(sat, N)  # we exercised both SAT and UNSAT

    def test_heuristic_configs_all_correct(self):
        """Every heuristic on/off combination must still be sound."""
        configs = [
            {}, {"use_vsids": False}, {"use_restarts": False},
            {"reduce_db": False}, {"use_vsids": False, "use_restarts": False},
        ]
        for i in range(120):
            c = random_at_ratio((i % 8) + 4, 4.2, seed=i + 999)
            exp, _ = brute_force(c)
            for cfg in configs:
                self.assertEqual(Solver(c, **cfg).solve(), exp,
                                 f"config {cfg} disagreed on seed {i}")


class TestHeuristicsFire(unittest.TestCase):
    def test_stats_nonzero(self):
        c = random_at_ratio(120, 4.3, seed=7)
        s = Solver(c, seed=7)
        s.solve()
        self.assertGreater(s.stats.conflicts, 0)
        self.assertGreater(s.stats.learned, 0)
        self.assertGreater(s.stats.restarts, 0)
        self.assertGreater(s.stats.decisions, 0)

    def test_db_reduction_fires(self):
        c = random_at_ratio(150, 4.3, seed=3)
        s = Solver(c, seed=3)
        s.solve()
        self.assertGreaterEqual(s.stats.db_reductions, 1)
        self.assertGreater(s.stats.deleted_clauses, 0)


class TestEncoders(unittest.TestCase):
    def test_queens(self):
        for n in (4, 6, 8):
            enc = encoders.encode_queens(n)
            s = Solver(enc.cnf)
            self.assertTrue(s.solve(), f"queens {n} should be SAT")
            self.assertTrue(self._valid_queens(enc.decode(s.model()), n))

    def test_queens_unsolvable(self):
        for n in (2, 3):
            self.assertFalse(Solver(encoders.encode_queens(n).cnf).solve(),
                             f"queens {n} should be UNSAT")

    @staticmethod
    def _valid_queens(board, n):
        rows = [r.split() for r in board.splitlines()]
        qs = [(i, j) for i, row in enumerate(rows)
              for j, ch in enumerate(row) if ch == "Q"]
        if len(qs) != n:
            return False
        for a in range(len(qs)):
            for b in range(a + 1, len(qs)):
                (r1, c1), (r2, c2) = qs[a], qs[b]
                if r1 == r2 or c1 == c2 or abs(r1 - r2) == abs(c1 - c2):
                    return False
        return True

    def test_sudoku(self):
        givens = ("53..7...." "6..195..." ".98....6." "8...6...3" "4..8.3..1"
                  "7...2...6" ".6....28." "...419..5" "....8..79")
        enc = encoders.encode_sudoku(givens)
        s = Solver(enc.cnf)
        self.assertTrue(s.solve())
        grid = self._grid_from_decode(enc.decode(s.model()))
        self.assertTrue(self._valid_sudoku(grid))
        # givens preserved
        flat = givens.replace(".", "0")
        for r in range(9):
            for c in range(9):
                if flat[r * 9 + c] != "0":
                    self.assertEqual(str(grid[r][c]), flat[r * 9 + c])

    @staticmethod
    def _grid_from_decode(text):
        grid = []
        for line in text.splitlines():
            if set(line) <= set("-+ "):
                continue
            digits = [int(ch) for ch in line if ch.isdigit()]
            if digits:
                grid.append(digits)
        return grid

    @staticmethod
    def _valid_sudoku(grid):
        full = set(range(1, 10))
        if len(grid) != 9 or any(len(r) != 9 for r in grid):
            return False
        for i in range(9):
            if set(grid[i]) != full:
                return False
            if {grid[r][i] for r in range(9)} != full:
                return False
        for br in range(3):
            for bc in range(3):
                box = {grid[br * 3 + i][bc * 3 + j] for i in range(3) for j in range(3)}
                if box != full:
                    return False
        return True

    def test_coloring(self):
        # K4 needs 4 colors: 3 is UNSAT, 4 is SAT.
        edges = [(a, b) for a in range(4) for b in range(a + 1, 4)]
        self.assertFalse(Solver(encoders.encode_coloring(4, edges, 3).cnf).solve())
        enc = encoders.encode_coloring(4, edges, 4)
        s = Solver(enc.cnf)
        self.assertTrue(s.solve())
        colors = self._colors_from_model(enc, s.model())
        for (u, v) in edges:
            self.assertNotEqual(colors[u], colors[v])

    @staticmethod
    def _colors_from_model(enc, model):
        true = {l for l in model if l > 0}
        # parse "vertex i: color k" lines
        out = {}
        for line in enc.decode(model).splitlines():
            parts = line.replace(":", "").split()
            out[int(parts[1])] = int(parts[3])
        return out

    def test_pigeonhole_unsat(self):
        for holes in (2, 3, 4):
            self.assertFalse(Solver(encoders.encode_pigeonhole(holes).cnf).solve())

    def test_pigeonhole_sat_when_fits(self):
        # equal pigeons and holes is satisfiable
        enc = encoders.encode_pigeonhole(holes=4, pigeons=4)
        self.assertTrue(Solver(enc.cnf).solve())

    def test_parse_graph(self):
        n, edges = encoders.parse_graph("4\n0 1\n1 2\n2 3\n")
        self.assertEqual(n, 4)
        self.assertEqual(edges, [(0, 1), (1, 2), (2, 3)])


class TestProofs(unittest.TestCase):
    def test_pigeonhole_proof(self):
        enc = encoders.encode_pigeonhole(4)
        s = Solver(enc.cnf, log_proof=True)
        self.assertFalse(s.solve())
        self.assertTrue(proofmod.check_proof(enc.cnf, s.proof))

    def test_random_unsat_proofs(self):
        verified = 0
        for seed in range(400):
            c = random_at_ratio(7, 4.8, seed=seed)
            exp, _ = brute_force(c)
            if exp:
                continue
            s = Solver(c, log_proof=True)
            self.assertFalse(s.solve())
            self.assertTrue(proofmod.check_proof(c, s.proof),
                            f"proof failed for seed {seed}")
            verified += 1
            if verified >= 25:
                break
        self.assertGreaterEqual(verified, 10)

    def test_trivial_unsat_proof(self):
        for c in [CNF(1, [[1], [-1]]), CNF(2, [[]])]:
            s = Solver(c, log_proof=True)
            self.assertFalse(s.solve())
            self.assertEqual(s.proof, [[]])
            self.assertTrue(proofmod.check_proof(c, s.proof))

    def test_proof_serialization_roundtrip(self):
        p = [[1, -2, 3], [4], []]
        txt = proofmod.serialize_proof(p)
        self.assertEqual(proofmod.parse_proof(txt), p)

    def test_bogus_proof_rejected(self):
        c = CNF(2, [[1, 2], [1, -2], [-1, 2], [-1, -2]])  # UNSAT
        # a proof that just jumps to empty without RUP support is rejected
        self.assertFalse(proofmod.check_proof(CNF(2, [[1, 2]]), [[]]))


class TestViz(unittest.TestCase):
    def test_render(self):
        c = random_at_ratio(40, 4.5, seed=5)
        s = Solver(c, record_conflict_graph=True, seed=5)
        s.solve()
        self.assertIsNotNone(s.conflict_graph)
        html = vizmod.render_html(s.conflict_graph)
        self.assertIn("<svg", html)
        self.assertIn("Learned clause", html)
        self.assertNotIn("{title}", html)  # no unfilled template braces
        rel, edges = vizmod.build_graph(s.conflict_graph)
        self.assertGreater(len(rel), 0)
        self.assertGreater(len(edges), 0)


class TestOracle(unittest.TestCase):
    def test_count_models(self):
        # (x1 or x2): 3 of 4 assignments satisfy
        self.assertEqual(count_models(CNF(2, [[1, 2]])), 3)
        # contradiction
        self.assertEqual(count_models(CNF(1, [[1], [-1]])), 0)

    def test_oracle_refuses_large(self):
        with self.assertRaises(ValueError):
            brute_force(CNF(40, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
