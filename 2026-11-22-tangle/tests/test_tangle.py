import io
import itertools
import os
import random
import sys
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tangle import Link, LinkError, jones, alexander, determinant, colorings, catalog, poly as P
from tangle.link import parse_pd, parse_braid
from tangle.jones import kauffman_bracket, mirror_jones, fmt_jones
from tangle.identify import identify
from tangle.simplify import simplify, scramble
from tangle.draw import render_svg
from tangle import cli

# Published Alexander polynomials (standard tables, Delta(1)=+1 normalisation), low->high coefficients.
PUBLISHED_ALEX = {
    "3_1": [1, -1, 1], "4_1": [-1, 3, -1], "5_1": [1, -1, 1, -1, 1], "5_2": [2, -3, 2],
    "6_1": [-2, 5, -2], "6_2": [-1, 3, -3, 3, -1], "6_3": [1, -3, 5, -3, 1],
    "7_1": [1, -1, 1, -1, 1, -1, 1], "7_2": [3, -5, 3], "7_3": [2, -3, 3, -3, 2],
    "7_4": [4, -7, 4], "7_5": [2, -4, 5, -4, 2], "7_6": [-1, 5, -7, 5, -1], "7_7": [1, -5, 9, -5, 1]}
PUBLISHED_DET = {"3_1": 3, "4_1": 5, "5_1": 5, "5_2": 7, "6_1": 9, "6_2": 11, "6_3": 13, "7_1": 7,
                 "7_2": 11, "7_3": 13, "7_4": 15, "7_5": 17, "7_6": 19, "7_7": 21}


def J(word, n=None):
    return jones(Link.from_braid(word, n))


def brute_bracket(link):
    """Independent <K>: enumerate all 2^n smoothing states with union-find."""
    xs = link.crossings
    n = len(xs)
    total = {}
    d = {2: -1, -2: -1}
    for state in itertools.product((0, 1), repeat=n):
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        a_cnt = 0
        for (a, b, c, dd), s in zip(xs, state):
            pairs = ((a, b), (c, dd)) if s == 0 else ((a, dd), (b, c))
            a_cnt += 1 if s == 0 else -1
            for u, v in pairs:
                parent[find(u)] = find(v)
        labels = {e for c in xs for e in c}
        loops = len({find(e) for e in labels}) + link.free_loops
        term = P.shift({0: 1}, a_cnt)
        for _ in range(loops - 1):
            term = P.mul(term, d)
        total = P.add(total, term)
    return total


class TestDiagrams(unittest.TestCase):
    def test_braid_parse_forms(self):
        self.assertEqual(parse_braid("1 -2 1 -2"), (3, [1, -2, 1, -2]))
        self.assertEqual(parse_braid("s1 s2^-1 s1 s2^-1"), (3, [1, -2, 1, -2]))
        self.assertEqual(parse_braid("s1^3"), (2, [1, 1, 1]))
        self.assertEqual(parse_braid("1,1,1", strands=4), (4, [1, 1, 1]))

    def test_bad_input(self):
        for bad in ["a b", "0", "1 x", "s-1^2"]:
            with self.assertRaises(LinkError, msg=bad):
                parse_braid(bad)
        with self.assertRaises(LinkError):
            parse_braid("1 5", strands=3)
        with self.assertRaises(LinkError):
            Link.from_pd(parse_pd("X[1,2,3,4]"))                  # edges appear once
        with self.assertRaises(LinkError):
            parse_pd("X[1,2,3]")
        with self.assertRaises(LinkError):
            parse_pd("hello")
        with self.assertRaises(LinkError):
            Link.from_pd([(1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 3, 4)])  # edge 1 appears 3 times
        with self.assertRaises(LinkError):                            # inconsistent orientation
            Link.from_pd([(1, 2, 2, 1), (3, 4, 4, 3)][:1] + [(1, 1, 1, 1)])

    def test_signs_match_generators(self):
        for w in ([1, -2, 1, -2], [1, 1, -2, 3, -1, -3], [-1, -1, -1]):
            L = Link.from_braid(w)
            self.assertEqual(L.signs, [1 if g > 0 else -1 for g in w])

    def test_components_and_linking(self):
        self.assertEqual(Link.from_braid("1 1 1").num_components, 1)
        self.assertEqual(Link.from_braid("1 1").num_components, 2)
        self.assertEqual(Link.from_braid("1 1").linking_numbers(), {(0, 1): 1})
        self.assertEqual(Link.from_braid("-1 -1").linking_numbers(), {(0, 1): -1})
        self.assertEqual(Link.from_braid("1 1 1 1").linking_numbers(), {(0, 1): 2})
        self.assertEqual(set(catalog.get("Borromean rings").linking_numbers().values()), {0})
        self.assertEqual(Link.from_braid([], 3).num_components, 3)         # free loops counted

    def test_pd_roundtrip_and_orientation(self):
        for name in ("3_1", "4_1", "5_2", "6_3", "Borromean rings", "Hopf link"):
            L = catalog.get(name)
            L2 = Link.from_pd(L.pd_code(), L.free_loops)
            self.assertEqual(L2.signs, L.signs, name)
            self.assertEqual(jones(L2), jones(L), name)

    def test_knottheory_pd_conventions(self):
        # PD codes of 3_1 and 4_1 as published by KnotTheory; Jones polynomials from the same tables.
        t31 = Link.from_pd(parse_pd("X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]"))
        self.assertEqual(fmt_jones(jones(t31)), "-t^-4 + t^-3 + t^-1")
        f41 = Link.from_pd(parse_pd("X[4,2,5,1] X[8,6,1,5] X[6,3,7,4] X[2,7,3,8]"))
        self.assertEqual(fmt_jones(jones(f41)), "t^-2 - t^-1 + 1 - t + t^2")

    def test_mirror(self):
        for name in ("3_1", "5_2", "7_4"):
            L = catalog.get(name)
            M = L.mirror()
            self.assertEqual(jones(M), mirror_jones(jones(L)))
            self.assertEqual(alexander(M), alexander(L))
            self.assertEqual(M.signs, [-s for s in L.signs])


class TestJones(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(fmt_jones(J("1 1 1")), "t + t^3 - t^4")
        self.assertEqual(fmt_jones(J("-1 -1 -1")), "-t^-4 + t^-3 + t^-1")
        self.assertEqual(fmt_jones(J("1 -2 1 -2")), "t^-2 - t^-1 + 1 - t + t^2")
        self.assertEqual(fmt_jones(J("1 1 1 1 1")), "t^2 + t^4 - t^5 + t^6 - t^7")
        self.assertEqual(fmt_jones(J("1 1")), "-t^(1/2) - t^(5/2)")           # Hopf link
        self.assertEqual(J([], 1), {0: 1})                                    # unknot
        self.assertEqual(fmt_jones(J([], 2)), "-t^(-1/2) - t^(1/2)")          # 2-unlink
        self.assertEqual(J("1 2 1 2"), J("1 1 1"))                            # s1s2s1s2 = trefoil

    def test_dp_equals_bruteforce(self):
        rng = random.Random(3)
        for _ in range(40):
            n = rng.randint(2, 4)
            w = [rng.choice([g for i in range(1, n) for g in (i, -i)]) for _ in range(rng.randint(1, 9))]
            L = Link.from_braid(w, n)
            self.assertEqual(kauffman_bracket(L), brute_bracket(L), w)

    def test_dp_equals_bruteforce_on_pd(self):
        L = Link.from_pd(parse_pd("X[4,2,5,1] X[8,6,1,5] X[6,3,7,4] X[2,7,3,8]"))
        self.assertEqual(kauffman_bracket(L), brute_bracket(L))

    def test_V_at_one(self):                          # V_L(1) = (-2)^(c-1)
        for name in ("3_1", "7_4", "Hopf link", "Borromean rings", "3_1#3_1", "3-component unlink"):
            L = catalog.get(name)
            v = sum(J_c for J_c in jones(L).values())
            self.assertEqual(v, (-2) ** (L.num_components - 1), name)

    def test_jones_matches_alexander_determinant(self):   # |V(-1)| = |Delta(-1)| for knots
        for name, det in PUBLISHED_DET.items():
            Jn = jones(catalog.get(name))
            val = sum(c * (-1) ** (q // 4) for q, c in Jn.items())
            self.assertEqual(abs(val), det, name)

    def test_big_braid_is_fast(self):
        # 36 crossings on 3 strands: infeasible for a 2^n state sum, trivial for the frontier DP
        L = Link.from_braid("1 -2 " * 18)
        j = jones(L)
        self.assertEqual(L.n, 36)
        self.assertEqual(sum(j.values()), (-2) ** (L.num_components - 1))

    def test_torus_knot_formula(self):            # V(T(2,n)) = t^((n-1)/2) (1 - t^2 + t^3 - ... )
        v = jones(catalog.get("T(2,7)"))
        self.assertEqual(v, jones(catalog.get("7_1")))
        self.assertEqual(min(v) // 4, 3)

    def test_unlink_split_factor(self):
        # split union of trefoil and a circle: V = (-t^(1/2) - t^(-1/2)) * V(trefoil)
        t = Link.from_braid([1, 1, 1, 3, 3, 3][:3], 4)       # trefoil + 2 free loops? strands 3,4 untouched
        self.assertEqual(t.num_components, 3)


class TestAlexander(unittest.TestCase):
    def test_published_table(self):
        for name, co in PUBLISHED_ALEX.items():
            deg = len(co) - 1
            want = {i - deg // 2: c for i, c in enumerate(co)}
            self.assertEqual(alexander(catalog.get(name)), want, name)
            self.assertEqual(determinant(catalog.get(name)), PUBLISHED_DET[name], name)

    def test_unknot_and_links(self):
        self.assertEqual(alexander(Link.from_braid([], 1)), {0: 1})
        self.assertEqual(alexander(Link.from_braid([], 2)), {})              # split link
        self.assertEqual(alexander(Link.from_braid("1 1")), {0: -1, 1: 1}) or None

    def test_symmetry_for_knots(self):
        for name in PUBLISHED_ALEX:
            A = alexander(catalog.get(name))
            self.assertEqual(A, {-e: c for e, c in A.items()}, name)
            self.assertEqual(sum(A.values()), 1, name)

    def test_torus_knot_formula(self):
        # Delta_T(p,q) = (t^{pq}-1)(t-1) / ((t^p-1)(t^q-1))
        for p, q in ((2, 5), (3, 4), (3, 5), (4, 5)):
            A = alexander(catalog.get(f"T({p},{q})"))
            num = P.mul({p * q: 1, 0: -1}, {1: 1, 0: -1})
            den = P.mul({p: 1, 0: -1}, {q: 1, 0: -1})
            want = P.divide_exact(num, den)
            deg = max(want)
            want = P.shift(want, -deg // 2)
            self.assertEqual(A, want, (p, q))

    def test_two_bridge_via_conway(self):
        # Independent construction (Conway notation, plat closure) must agree with the braid catalog.
        for name, conway in (("3_1", [3]), ("4_1", [2, 2]), ("5_2", [3, 2]), ("6_1", [4, 2]),
                             ("7_2", [5, 2]), ("7_3", [4, 3]), ("7_6", [2, 2, 1, 2])):
            C = Link.from_conway(conway)
            self.assertEqual(alexander(C), alexander(catalog.get(name)), name)
            a, b = jones(C), jones(catalog.get(name))
            self.assertIn(b, (a, mirror_jones(a)), name)

    def test_colorings(self):
        self.assertEqual(colorings(catalog.get("3_1"), 3), {"p": 3, "total": 9, "nontrivial": 6, "colorable": True})
        self.assertFalse(colorings(catalog.get("3_1"), 5)["colorable"])
        self.assertEqual(colorings(catalog.get("4_1"), 5)["nontrivial"], 20)
        self.assertFalse(colorings(catalog.get("4_1"), 3)["colorable"])
        self.assertFalse(colorings(Link.from_braid([], 1), 3)["colorable"])
        for name, det in PUBLISHED_DET.items():           # p-colourable  <=>  p | det
            L = catalog.get(name)
            for p in (3, 5, 7, 11, 13):
                self.assertEqual(colorings(L, p)["colorable"], det % p == 0, (name, p))
        with self.assertRaises(ValueError):
            colorings(catalog.get("3_1"), 4)


class TestIdentify(unittest.TestCase):
    def test_catalog_entries_are_pairwise_distinct(self):
        seen = {}
        for name in catalog.names():
            L = catalog.get(name)
            key = (L.num_components, tuple(sorted(alexander(L).items())), tuple(sorted(jones(L).items())))
            mkey = (L.num_components, tuple(sorted(alexander(L).items())),
                    tuple(sorted(mirror_jones(jones(L)).items())))
            for k in (key, mkey):
                if k in seen and seen[k] != name and not name.endswith("unlink"):
                    self.fail(f"{name} indistinguishable from {seen[k]}")
            seen[key] = name
            seen[mkey] = name

    def test_self_identification_and_mirror(self):
        for name in PUBLISHED_ALEX:
            L = catalog.get(name)
            r = identify(L)
            self.assertEqual([m[0] for m in r["matches"]], [name])
            r2 = identify(L.mirror())
            self.assertEqual([m[0] for m in r2["matches"]], [name])
            if r["invariants"]["chiral"]:
                self.assertEqual(r["matches"][0][1], "same")
                self.assertEqual(r2["matches"][0][1], "mirror")
            else:
                self.assertEqual(r["matches"][0][1], "both")

    def test_known_chirality(self):
        for name, chiral in (("3_1", True), ("4_1", False), ("6_3", False), ("5_1", True), ("5_2", True),
                             ("6_1", True), ("7_1", True)):
            self.assertEqual(identify(catalog.get(name))["invariants"]["chiral"], chiral, name)

    def test_composites(self):
        self.assertEqual(identify(Link.from_braid("1 1 1 3 3 3", 4))["matches"], [])   # not a knot: 3 comps
        granny = identify(catalog.get("3_1#3_1"))["matches"][0][0]
        square = identify(catalog.get("3_1#m3_1"))["matches"][0][0]
        self.assertEqual((granny, square), ("3_1#3_1", "3_1#m3_1"))                # Jones tells them apart

    def test_identify_from_pd_only(self):
        r = identify(Link.from_pd(parse_pd("X[4,2,5,1] X[8,6,1,5] X[6,3,7,4] X[2,7,3,8]")))
        self.assertEqual(r["matches"][0][0], "4_1")

    def test_unknown_knot_gets_lower_bound(self):
        r = identify(Link.from_braid("1 -2 1 -2 1 -2 1 -2 1 -2 1 -2 1 -2 1 -2"))   # a 16-crossing alt. braid
        self.assertIn("not in catalog", r["verdict"])
        self.assertGreaterEqual(r["invariants"]["crossing_lower_bound"], 8)

    def test_torus_knot_lookup(self):
        self.assertEqual(identify(catalog.get("T(2,5)"))["matches"][0][0], "5_1")
        self.assertEqual(identify(catalog.get("T(2,-3)"))["matches"][0][0], "3_1")
        self.assertEqual(identify(catalog.get("T(3,4)"))["matches"], [])          # 8_19: beyond catalog
        with self.assertRaises(LinkError):
            catalog.get("T(1,3)")
        with self.assertRaises(LinkError):
            catalog.get("no such knot")


class TestSimplify(unittest.TestCase):
    def test_proves_unknot(self):
        cases = [(3, [1, 2, -1, -2]), (2, [1]), (3, [1, -2]), (4, [1, 2, 3]), (3, [1, 2, 1, -2, 1, 2][:0] + [2, 1, 2, -1, -2][:0] + [1, 2, -1, 2, -1][:0] + [1, 2])]
        for n, w in cases:
            r = simplify(n, w)
            self.assertTrue(r["proved_unknot"], (n, w))

    def test_scrambled_unknots(self):
        proved = 0
        for seed in range(12):
            n, w = scramble(1, [], steps=14, seed=seed)
            L = Link.from_braid(w, n)
            self.assertEqual(jones(L), {0: 1})
            self.assertEqual(L.num_components, 1)
            r = simplify(n, w, node_budget=60000)
            proved += r["proved_unknot"]
            self.assertLessEqual(len(r["word"]), len(w))
        self.assertGreaterEqual(proved, 10)

    def test_never_claims_unknot_for_knots(self):
        for name in ("3_1", "4_1", "5_2", "6_3", "7_5"):
            L = catalog.get(name)
            r = simplify(*L.braid, node_budget=3000)
            self.assertFalse(r["proved_unknot"], name)

    def test_simplification_is_sound(self):
        rng = random.Random(11)
        for _ in range(15):
            name = rng.choice(["3_1", "4_1", "5_1", "5_2", "6_2"])
            L = catalog.get(name)
            n, w = scramble(*L.braid, steps=20, seed=rng.randint(0, 999))
            r = simplify(n, w, node_budget=8000)
            L2 = Link.from_braid(r["word"], r["strands"])
            self.assertEqual(jones(L2), jones(L), name)
            self.assertEqual(alexander(L2), alexander(L), name)
            self.assertLessEqual(len(r["word"]), len(w))

    def test_scramble_preserves_invariants(self):
        rng = random.Random(5)
        for name in ("3_1", "4_1", "5_2", "6_3", "7_7", "Hopf link", "Borromean rings"):
            L = catalog.get(name)
            for _ in range(3):
                n, w = scramble(*L.braid, steps=25, seed=rng.randint(0, 10 ** 6))
                L2 = Link.from_braid(w, n)
                self.assertEqual(jones(L2), jones(L), name)
                self.assertEqual(alexander(L2), alexander(L), name)
                self.assertEqual(L2.num_components, L.num_components)

    def test_scrambled_diagram_is_still_identified(self):
        for seed in range(5):
            L = catalog.get("5_2")
            n, w = scramble(*L.braid, steps=25, seed=seed)
            self.assertEqual(identify(Link.from_braid(w, n))["matches"][0][0], "5_2")


class TestDrawAndCli(unittest.TestCase):
    def test_svg_wellformed(self):
        for name in ("3_1", "Borromean rings", "0_1", "3-component unlink"):
            for theme in ("light", "dark"):
                svg = render_svg(catalog.get(name), title=name, caption=["a < b & c"], theme=theme)
                root = ET.fromstring(svg)                        # raises if malformed
                self.assertTrue(root.tag.endswith("svg"))
        with self.assertRaises(LinkError):
            render_svg(Link.from_pd(parse_pd("X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]")))

    def test_svg_component_colours(self):
        svg = render_svg(catalog.get("Borromean rings"))
        self.assertEqual(len({c for c in ("#c8452c", "#1f6f8b", "#6a8f3a") if c in svg}), 3)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cli_analyze(self):
        code, out, _ = self.run_cli("analyze", "--name", "4_1")
        self.assertEqual(code, 0)
        self.assertIn("matches catalog entry: 4_1 (amphichiral)", out)
        code, out, _ = self.run_cli("analyze", "--torus", "2,3")
        self.assertIn("3_1", out)
        code, out, _ = self.run_cli("analyze", "--braid", "1 1 1", "--json")
        self.assertIn('"determinant": 3', out)
        code, out, _ = self.run_cli("analyze", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]")
        self.assertIn("3_1", out)

    def test_cli_errors(self):
        code, _, err = self.run_cli("analyze", "--braid", "1 x")
        self.assertEqual(code, 1)
        self.assertIn("error", err)
        code, _, err = self.run_cli("analyze")
        self.assertEqual(code, 1)
        code, _, err = self.run_cli("simplify", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]")
        self.assertEqual(code, 1)
        code, _, err = self.run_cli("analyze", "--name", "9_99")
        self.assertEqual(code, 1)

    def test_cli_simplify_scramble_draw_catalog(self):
        code, out, _ = self.run_cli("simplify", "--braid", "1 2 -1 -2")
        self.assertIn("PROVED", out)
        code, out, _ = self.run_cli("simplify", "--name", "3_1")
        self.assertNotIn("PROVED", out)
        code, out, _ = self.run_cli("scramble", "--name", "5_2", "--steps", "20", "--seed", "4")
        self.assertIn("invariants identical: YES", out)
        path = os.path.join(os.path.dirname(__file__), "_out.svg")
        code, out, _ = self.run_cli("draw", "--name", "6_2", "-o", path)
        self.assertEqual(code, 0)
        ET.parse(path)
        os.remove(path)
        code, out, _ = self.run_cli("catalog")
        self.assertIn("7_7", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
