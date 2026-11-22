"""Regression tests for every finding in REVIEW.md (each fails on the phase-2 code)."""
import io
import os
import random
import sys
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tangle import Link, LinkError, jones, alexander, colorings, catalog, poly as P, cli
from tangle.alexander import alexander_matrix_at, alexander_raw, arcs, _det
from tangle.identify import identify
from tangle.jones import jones_orientations, kauffman_bracket, _jones_from_bracket
from tangle.link import parse_pd
from tangle.simplify import scramble


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def reverse_component(link, comp):
    """PD of the same diagram with one component's orientation reversed (needs an under pass)."""
    xs = [tuple(c) for c in link.crossings]
    for k in range(link.n):
        if link._comp_of[(k, 0)] == comp:
            xs[k] = xs[k][2:] + xs[k][:2]
    return Link.from_pd(xs, link.free_loops)


class Finding1_Planarity(unittest.TestCase):
    def test_swapped_labels_rejected(self):
        with self.assertRaisesRegex(LinkError, "not a planar"):
            Link.from_pd(parse_pd("X[1,5,2,4] X[3,6,4,1] X[5,2,6,3]"))

    def test_all_builtin_diagrams_are_planar(self):
        for n in catalog.names():
            catalog.get(n)

    def test_fuzz_mutated_pds_never_crash(self):
        rng = random.Random(1234)
        accepted = rejected = 0
        for _ in range(300):
            L = catalog.get(rng.choice(["3_1", "4_1", "5_2", "6_3", "7_5", "Borromean rings"]))
            xs = [list(c) for c in L.pd_code()]
            for _ in range(rng.randint(1, 2)):
                k = rng.randrange(len(xs))
                rng.shuffle(xs[k]) if rng.random() < 0.5 else xs[k].reverse()
            try:
                M = Link.from_pd([tuple(c) for c in xs])
            except LinkError:
                rejected += 1
                continue
            accepted += 1
            j = jones(M)                                     # must be computable and sane
            self.assertEqual(sum(j.values()), (-2) ** (M.num_components - 1))
        self.assertGreater(rejected, 100)


class Finding2_LinkColorings(unittest.TestCase):
    def test_unlink_and_links(self):
        self.assertEqual(colorings(Link.from_braid([], 2), 3)["nontrivial"], 6)
        self.assertEqual(colorings(Link.from_braid([], 3), 3)["total"], 27)
        self.assertFalse(colorings(catalog.get("Hopf link"), 3)["colorable"])
        self.assertFalse(colorings(catalog.get("Solomon link"), 3)["colorable"])       # det 4
        self.assertFalse(colorings(catalog.get("Borromean rings"), 3)["colorable"])    # det 16
        self.assertTrue(colorings(catalog.get("T(2,6) link"), 3)["colorable"])   # det 6


class Finding3_LinkOrientation(unittest.TestCase):
    def test_reversed_component_still_identified(self):
        for name in ("Solomon link", "Hopf link", "T(2,6) link", "Borromean rings"):
            L = catalog.get(name)
            R = reverse_component(L, 1)
            self.assertEqual([m[0] for m in identify(R)["matches"]], [name], name)
            self.assertEqual([m[0] for m in identify(L)["matches"]], [name], name)
        L = catalog.get("Solomon link")
        R = reverse_component(L, 1)
        self.assertNotEqual(jones(L), jones(R))                      # the orientation really matters
        self.assertIn(jones(R), [j for _, j in jones_orientations(L)])

    def test_orientation_variants_match_direct_computation(self):
        L = catalog.get("Borromean rings")
        variants = [j for _, j in jones_orientations(L)]
        for comp in (1, 2):
            self.assertIn(jones(reverse_component(L, comp)), variants)
        self.assertEqual(len(variants), 4)


class Finding4_ParsePd(unittest.TestCase):
    def test_strict(self):
        for bad in ("abc 1 2 3 4 xyz", "X[1.5,2,3,4]", "X[1,2,3,4-]", "X[1-2,3,4,5]", ""):
            with self.assertRaises(LinkError, msg=bad):
                parse_pd(bad)
        self.assertEqual(parse_pd("X[1,4,2,5], X[3,6,4,1]"), [(1, 4, 2, 5), (3, 6, 4, 1)])
        self.assertEqual(parse_pd("[[1,4,2,5],[3,6,4,1]]"), [(1, 4, 2, 5), (3, 6, 4, 1)])


class Finding5_ModularAlexander(unittest.TestCase):
    def test_equals_fraction_reference(self):
        def ref(L):
            n = L.n
            pts = [Fraction(i) for i in range(n + 1)]
            vals = []
            for t0 in pts:
                M, _ = alexander_matrix_at(L, t0)
                vals.append(_det([r[:-1] for r in M[:-1]]))
            return {e: int(c) for e, c in enumerate(P.interpolate(pts, vals)) if c}
        rng = random.Random(9)
        tested = 0
        while tested < 120:
            n = rng.randint(2, 5)
            w = [rng.choice([g for i in range(1, n) for g in (i, -i)]) for _ in range(rng.randint(2, 11))]
            L = Link.from_braid(w, n)
            if arcs(L)[0] != L.n or L.free_loops:
                continue
            tested += 1
            self.assertEqual(alexander_raw(L), ref(L), w)

    def test_speed_100_crossings(self):
        t = time.time()
        A = alexander(Link.from_braid("1 -2 " * 50))
        self.assertLess(time.time() - t, 5)
        self.assertEqual(sum(A.values()), 1)
        self.assertEqual(A, {-e: c for e, c in A.items()})


class Finding6_JonesSelfCheck(unittest.TestCase):
    def test_impossible_exponent_detected(self):
        with self.assertRaises(ArithmeticError):
            _jones_from_bracket({1: 1}, 0, 1)         # bracket exponent 1 can never occur for a knot
        self.assertEqual(_jones_from_bracket({0: 1}, 0, 1), {0: 1})


class Finding7_Scramble(unittest.TestCase):
    def test_stays_readable(self):
        L = catalog.get("6_3")
        for seed in range(20):
            n, w = scramble(*L.braid, steps=40, seed=seed)
            self.assertLessEqual(len(w), len(L.braid[1]) + 8)


class Finding8_WideDiagramCap(unittest.TestCase):
    def test_cap(self):
        rng = random.Random(2)
        w = [rng.choice([g for i in range(1, 8) for g in (i, -i)]) for _ in range(60)]
        L = Link.from_braid(w, 8)
        with self.assertRaisesRegex(MemoryError, "too wide"):
            kauffman_bracket(L, max_states=50)
        code, out, err = run_cli("analyze", "--braid", " ".join(map(str, w)), "--strands", "8")
        self.assertIn(code, (0, 1))                  # either answers or fails cleanly, never a traceback


class Finding9_10_11_CliWording(unittest.TestCase):
    def test_simplify_wording(self):
        code, out, _ = run_cli("simplify", "--braid", "1 -1", "--strands", "3")
        self.assertIn("3-component unlink", out)
        code, out, _ = run_cli("simplify", "--name", "4_1")
        self.assertIn("Not the unknot", out)
        self.assertNotIn("knottedness", out)
        code, out, _ = run_cli("simplify", "--name", "Hopf link")
        self.assertIn("link", out.lower())

    def test_formatting(self):
        code, out, _ = run_cli("analyze", "--name", "Borromean rings")
        self.assertNotIn("+0", out)
        self.assertIn("lk(1,2) = 0", out)
        code, out, _ = run_cli("analyze", "--name", "0_1")
        self.assertIn("(no crossings)", out)
        self.assertNotIn("achiral-looking", out)

    def test_ignored_flags_error(self):
        code, _, err = run_cli("analyze", "--name", "3_1", "--strands", "5")
        self.assertEqual(code, 1)
        self.assertIn("--strands", err)
        code, _, err = run_cli("analyze", "--braid", "1 1 1", "--loops", "2")
        self.assertEqual(code, 1)
        code, _, err = run_cli("analyze", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]", "--loops", "-1")
        self.assertEqual(code, 1)


class Finding13_Verdict(unittest.TestCase):
    def test_bound_wording(self):
        code, out, _ = run_cli("analyze", "--torus", "3,4")
        self.assertIn("tight for alternating", out)


if __name__ == "__main__":
    unittest.main()
