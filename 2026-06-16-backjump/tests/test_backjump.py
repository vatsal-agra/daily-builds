"""Test suite for Backjump — exercises every feature.

Run:  python3 -m unittest discover -s tests   (from the project root)
   or: python3 tests/test_backjump.py
"""

import os
import sys
import random
import shutil
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backjump.cnf import CNF, parse_dimacs
from backjump.solver import Solver, SAT, UNSAT, luby
from backjump.proof import check_model, check_proof
from backjump.brute import brute_is_sat, brute_solve, count_models as brute_count
from backjump.encoders import Sudoku, NQueens, GraphColoring, Pigeonhole
from backjump.modelcount import count_models, all_models
from backjump.viz import build_bundle, generate_html
from backjump.cli import main, random_ksat, _validate_sudoku


def solve(cnf, **kw):
    s = Solver(cnf, **kw)
    return s.solve(), s


# ---------------------------------------------------------------------------
class TestCNFParsing(unittest.TestCase):
    def test_roundtrip(self):
        c = CNF()
        c.add_clause([1, -2, 3]); c.add_clause([-1, 2]); c.add_clause([3])
        back = parse_dimacs(c.to_dimacs())
        self.assertEqual(back.num_vars, 3)
        self.assertEqual(back.clauses, c.clauses)

    def test_comments_blanklines_multiline(self):
        txt = "c hi\np cnf 3 3\n\n1 -2 0\n2 3\n0\n-1 -3 0\n"
        c = parse_dimacs(txt)
        self.assertEqual(c.num_vars, 3)
        self.assertEqual(c.clauses, [[1, -2], [2, 3], [-1, -3]])

    def test_percent_terminator_and_missing_zero(self):
        txt = "p cnf 2 2\n1 2 0\n-1 -2\n%\n0\n"
        c = parse_dimacs(txt)
        self.assertEqual(c.clauses, [[1, 2], [-1, -2]])

    def test_bad_token_raises(self):
        with self.assertRaises(ValueError):
            parse_dimacs("p cnf 1 1\nfoo bar 0\n")


class TestLuby(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual([luby(i) for i in range(1, 16)],
                         [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8])


class TestSolverBasics(unittest.TestCase):
    def test_trivial_sat(self):
        c = CNF(); c.add_clause([1, 2]); c.add_clause([-1, 2]); c.add_clause([-2, 3])
        r, s = solve(c)
        self.assertEqual(r, SAT)
        self.assertTrue(check_model(c.clauses, s.model()))

    def test_trivial_unsat(self):
        c = CNF(); c.add_clause([1]); c.add_clause([-1])
        r, s = solve(c, emit_proof=True)
        self.assertEqual(r, UNSAT)
        ok, _ = check_proof(c.clauses, s.proof)
        self.assertTrue(ok)

    def test_unit_propagation_at_root(self):
        # decided purely by top-level implication: 0 decisions
        c = CNF(); c.add_clause([1]); c.add_clause([-1, 2]); c.add_clause([-2, 3])
        r, s = solve(c)
        self.assertEqual(r, SAT)
        self.assertEqual(s.stats.decisions, 0)
        self.assertTrue(check_model(c.clauses, s.model()))

    def test_empty_clause_is_unsat(self):
        c = CNF(2); c.add_clause([]); c.add_clause([1])
        r, _ = solve(c)
        self.assertEqual(r, UNSAT)

    def test_no_clauses_is_sat(self):
        c = CNF(3)
        r, s = solve(c)
        self.assertEqual(r, SAT)

    def test_duplicate_literals_and_tautologies(self):
        # [1,1,2] dedups to [1,2]; [1,-1] is a tautology
        c = CNF(); c.add_clause([1, 1, 2]); c.add_clause([1, -1]); c.add_clause([-1])
        r, s = solve(c, emit_proof=True)
        self.assertEqual(r, SAT)
        self.assertTrue(check_model(c.clauses, s.model()))

    def test_contradictory_units(self):
        c = CNF(); c.add_clause([2, 1]); c.add_clause([-1]); c.add_clause([1])
        r, _ = solve(c)
        self.assertEqual(r, UNSAT)


class TestDifferentialFuzz(unittest.TestCase):
    def test_vs_brute_force(self):
        rng = random.Random(20260616)
        nsat = nunsat = 0
        for _ in range(1500):
            nv = rng.randint(1, 9)
            cnf = random_ksat(nv, rng.randint(0, nv * 5), rng.randint(1, 4), rng)
            r, s = solve(cnf, emit_proof=True)
            truth = brute_is_sat(nv, cnf.clauses)
            self.assertEqual(r == SAT, truth, msg=f"{cnf.clauses}")
            if r == SAT:
                nsat += 1
                self.assertTrue(check_model(cnf.clauses, s.model()), msg=f"{cnf.clauses}")
            else:
                nunsat += 1
                ok, m = check_proof(cnf.clauses, s.proof)
                self.assertTrue(ok, msg=f"{cnf.clauses}: {m}")
        self.assertGreater(nsat, 100)
        self.assertGreater(nunsat, 100)

    def test_dirty_clauses_fuzz(self):
        # deliberately inject duplicate / complementary literals
        rng = random.Random(11)
        for _ in range(1500):
            nv = rng.randint(1, 8)
            cnf = CNF(nv)
            for _ in range(rng.randint(0, nv * 5)):
                w = rng.randint(1, 5)
                cnf.add_clause([rng.randint(1, nv) * (1 if rng.random() < .5 else -1)
                                for _ in range(w)])
            r, s = solve(cnf, emit_proof=True)
            self.assertEqual(r == SAT, brute_is_sat(nv, cnf.clauses), msg=f"{cnf.clauses}")
            if r == SAT:
                self.assertTrue(check_model(cnf.clauses, s.model()))
            else:
                self.assertTrue(check_proof(cnf.clauses, s.proof)[0], msg=f"{cnf.clauses}")


class TestProofChecker(unittest.TestCase):
    def test_rejects_bogus_proof(self):
        # a satisfiable formula has no refutation; an invented proof must fail
        c = CNF(); c.add_clause([1, 2])
        ok, _ = check_proof(c.clauses, [[1], [-1], []])  # claims unit 1 and -1
        self.assertFalse(ok)

    def test_empty_proof_rejected(self):
        c = CNF(); c.add_clause([1]); c.add_clause([-1])
        ok, _ = check_proof(c.clauses, [])
        self.assertFalse(ok)

    def test_proof_must_end_with_empty_clause(self):
        c = CNF(); c.add_clause([1]); c.add_clause([-1])
        ok, _ = check_proof(c.clauses, [[1]])
        self.assertFalse(ok)

    def test_duplicate_literal_unit_propagates(self):
        # [3,3] is logically the unit [3]; checker must use it
        ok, _ = check_proof([[3, 3], [-3]], [[]])
        self.assertTrue(ok)


class TestEncoders(unittest.TestCase):
    SUDOKU = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"

    def test_sudoku_solves_and_validates(self):
        sk = Sudoku(9)
        grid = sk.parse_grid(self.SUDOKU)
        r, s = solve(sk.encode(grid))
        self.assertEqual(r, SAT)
        sol = sk.decode(s.model())
        self.assertTrue(_validate_sudoku(sk, grid, sol))

    def test_sudoku_4x4(self):
        sk = Sudoku(4)
        grid = sk.parse_grid("1.3." "...." "...." ".4.2", 4)  # 16 cells, a couple givens
        r, s = solve(sk.encode(grid))
        self.assertEqual(r, SAT)
        self.assertTrue(_validate_sudoku(sk, grid, sk.decode(s.model())))

    def test_invalid_sudoku_unsat(self):
        sk = Sudoku(9)
        grid = sk.parse_grid("55" + "." * 79)
        self.assertEqual(solve(sk.encode(grid))[0], UNSAT)

    def test_sudoku_bad_length_raises(self):
        with self.assertRaises(ValueError):
            Sudoku(9).parse_grid("123")

    def test_queens(self):
        # n=1 SAT, n=2,3 UNSAT, n>=4 SAT
        self.assertEqual(solve(NQueens(1).encode())[0], SAT)
        self.assertEqual(solve(NQueens(2).encode())[0], UNSAT)
        self.assertEqual(solve(NQueens(3).encode())[0], UNSAT)
        for n in (4, 6, 8, 10):
            r, s = solve(NQueens(n).encode())
            self.assertEqual(r, SAT)
            cols = NQueens(n).decode(s.model())
            for i in range(n):
                for j in range(i + 1, n):
                    self.assertTrue(cols[i] != cols[j] and abs(cols[i] - cols[j]) != abs(i - j))

    def test_queens_unsat_has_proof(self):
        c = NQueens(3).encode()
        r, s = solve(c, emit_proof=True)
        self.assertEqual(r, UNSAT)
        self.assertTrue(check_proof(c.clauses, s.proof)[0])

    def test_coloring(self):
        edges = [(i, (i + 1) % 5) for i in range(5)]  # C5
        self.assertEqual(solve(GraphColoring(5, edges, 2).encode())[0], UNSAT)
        r, s = solve(GraphColoring(5, edges, 3).encode())
        self.assertEqual(r, SAT)
        cols = GraphColoring(5, edges, 3).decode(s.model())
        self.assertTrue(all(cols[a] != cols[b] for a, b in edges))

    def test_complete_graph_needs_n_colors(self):
        edges = [(i, j) for i in range(4) for j in range(i + 1, 4)]  # K4
        self.assertEqual(solve(GraphColoring(4, edges, 3).encode())[0], UNSAT)
        self.assertEqual(solve(GraphColoring(4, edges, 4).encode())[0], SAT)

    def test_pigeonhole(self):
        # p <= h SAT; p > h UNSAT (with verified proof)
        self.assertEqual(solve(Pigeonhole(3, 3).encode())[0], SAT)
        for p in (3, 4, 5, 6):
            c = Pigeonhole(p, p - 1).encode()
            r, s = solve(c, emit_proof=True)
            self.assertEqual(r, UNSAT)
            self.assertTrue(check_proof(c.clauses, s.proof)[0])


class TestModelCounting(unittest.TestCase):
    def test_count_matches_brute(self):
        rng = random.Random(3)
        for _ in range(40):
            nv = rng.randint(1, 7)
            cnf = random_ksat(nv, rng.randint(0, nv * 3), 3, rng)
            self.assertEqual(count_models(cnf), brute_count(cnf.num_vars, cnf.clauses),
                             msg=f"{cnf.clauses}")

    def test_all_models_are_distinct_and_valid(self):
        cnf = random_ksat(6, 10, 3, random.Random(8))
        models = list(all_models(cnf))
        seen = set(tuple(m) for m in models)
        self.assertEqual(len(seen), len(models))
        for m in models:
            self.assertTrue(check_model(cnf.clauses, m))

    def test_unsat_counts_zero(self):
        c = CNF(); c.add_clause([1]); c.add_clause([-1])
        self.assertEqual(count_models(c), 0)


# ---------------------------------------------------------------------------
# A Python port of the visualizer's JS replay, to verify traces are correct
# and faithfully reconstructable (the browser uses the same logic).
def replay_state(events):
    assign = {}       # var -> (val, level)
    trail = []        # (var, level)
    level = 0
    result = None
    for e in events:
        t = e["type"]
        if t == "decision":
            level = e["level"]
            v = abs(e["lit"])
            assign[v] = (e["lit"] > 0, level)
            trail.append((v, level))
        elif t == "propagate":
            v = abs(e["lit"])
            if v not in assign:
                assign[v] = (e["lit"] > 0, e["level"])
                trail.append((v, e["level"]))
        elif t == "backjump":
            level = e["level"]
            trail = [(v, lv) for (v, lv) in trail if lv <= level]
            assign = {v: a for v, a in assign.items() if a[1] <= level}
        elif t == "restart":
            level = 0
            trail = [(v, lv) for (v, lv) in trail if lv <= 0]
            assign = {v: a for v, a in assign.items() if a[1] <= 0}
        elif t in ("sat", "unsat"):
            result = t
    return assign, trail, result


class TestVisualizerTrace(unittest.TestCase):
    def test_sat_trace_replays_to_a_model(self):
        edges = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 4), (3, 4), (1, 4)]
        cnf = GraphColoring(5, edges, 3).encode()
        b = build_bundle(cnf, "viz test")
        self.assertEqual(b["result"], SAT)
        assign, trail, result = replay_state(b["events"])
        self.assertEqual(result, "sat")
        # the reconstructed assignment must satisfy every clause
        val = {v: a[0] for v, a in assign.items()}
        self.assertTrue(check_model(cnf.clauses, val))
        # trail and assignment stay in sync, levels monotonic
        self.assertEqual(len(trail), len(assign))

    def test_unsat_trace_ends_with_marker(self):
        cnf = Pigeonhole(4, 3).encode()
        b = build_bundle(cnf, "php viz")
        self.assertEqual(b["result"], UNSAT)
        self.assertEqual(b["events"][-1]["type"], "unsat")
        _, _, result = replay_state(b["events"])
        self.assertEqual(result, "unsat")

    def test_trail_assignment_sync_every_prefix(self):
        cnf = Pigeonhole(4, 3).encode()
        b = build_bundle(cnf, "php viz")
        for i in range(len(b["events"])):
            assign, trail, _ = replay_state(b["events"][:i + 1])
            self.assertEqual(len(trail), len(assign))

    def test_html_generates_and_is_selfcontained(self):
        cnf = NQueens(5).encode()
        html = generate_html(build_bundle(cnf, "q5"))
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("DATA", html)
        # no external resource loads (the only http:// is the SVG xmlns namespace)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("@import", html)


class TestJSSyntax(unittest.TestCase):
    def test_embedded_js_has_no_syntax_errors(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        html = generate_html(build_bundle(NQueens(5).encode(), "q5"))
        js = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
            path = f.name
        try:
            res = subprocess.run([node, "--check", path], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, msg=res.stderr)
        finally:
            os.unlink(path)


class TestCLI(unittest.TestCase):
    def test_queens_cmd(self):
        self.assertEqual(main(["queens", "8"]), 0)

    def test_pigeon_cmd(self):
        self.assertEqual(main(["pigeon", "5", "4"]), 0)

    def test_fuzz_cmd_returns_zero(self):
        self.assertEqual(main(["fuzz", "--trials", "100", "--vars", "7", "--seed", "1"]), 0)

    def test_count_cmd(self):
        self.assertEqual(main(["count", "--vars", "6", "--clauses", "8", "--check"]), 0)

    def test_gen_and_solve_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.cnf")
            self.assertEqual(main(["gen", "--vars", "30", "--clauses", "120",
                                   "--seed", "2", "--out", path]), 0)
            self.assertEqual(main(["solve", path]), 0)

    def test_viz_cmd_writes_html(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "v.html")
            self.assertEqual(main(["viz", "pigeon", "--pigeons", "4",
                                   "--holes", "3", "--out", path]), 0)
            self.assertTrue(os.path.getsize(path) > 1000)

    def test_missing_file_is_clean_error(self):
        self.assertEqual(main(["solve", "/no/such/file.cnf"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
