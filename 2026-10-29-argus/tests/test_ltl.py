import random
import unittest

from argus.lang import parse_ltl_text
from argus.ltl import eval_lasso, gpvw, nnf, to_buchi, fmt_core

NAT = 3


def rand_formula(rng, depth):
    if depth == 0 or rng.random() < 0.15:
        r = rng.random()
        if r < 0.05:
            return ("true",)
        if r < 0.1:
            return ("false",)
        return ("ap", rng.randrange(NAT))
    op = rng.choice(["not", "and", "or", "imp", "iff", "X", "F", "G", "U", "R", "W", "U", "X"])
    if op in ("not", "X", "F", "G"):
        return (op, rand_formula(rng, depth - 1))
    return (op, rand_formula(rng, depth - 1), rand_formula(rng, depth - 1))


def rand_word(rng):
    n = rng.randint(1, 6)
    vals = [rng.randrange(1 << NAT) for _ in range(n)]
    return vals, rng.randrange(n)


class LtlTests(unittest.TestCase):
    def test_buchi_matches_direct_semantics(self):
        rng = random.Random(20261029)
        checked = 0
        for _ in range(400):
            f = rand_formula(rng, rng.randint(1, 4))
            neg_aut = gpvw(nnf(f, False))
            pos_aut = gpvw(nnf(f, True))
            core = nnf(f, True)
            for _ in range(12):
                vals, k = rand_word(rng)
                truth = eval_lasso(core, vals, k)[0]
                # automaton for ¬f accepts exactly the words where f is false
                self.assertEqual(neg_aut.accepts_lasso(vals, k), not truth, (f, vals, k))
                self.assertEqual(pos_aut.accepts_lasso(vals, k), truth, (f, vals, k))
                checked += 1
        self.assertGreater(checked, 4000)

    def test_known_validities(self):
        # G(p) -> p ; F G p -> G F p ; (p U q) -> F q  are valid: ¬ automaton is empty on every word
        rng = random.Random(1)
        for text in ["[]p -> p", "<>[]p -> []<>p", "(p U q) -> <>q", "!(<>p) <-> [](!p)", "(p W q) <-> ([]p || (p U q))"]:
            f = parse_ltl_text(text)
            f = _atomize(f)
            aut = to_buchi(f)
            for _ in range(300):
                vals, k = rand_word(rng)
                self.assertFalse(aut.accepts_lasso(vals, k), text)

    def test_parser_precedence_and_atoms(self):
        f = parse_ltl_text("[](a == 1 && b + 1 < 3 -> <>(c))")
        self.assertEqual(f[0], "G")
        self.assertEqual(f[1][0], "imp")
        self.assertEqual(f[1][1][0], "and")
        g = parse_ltl_text("([] p) U (x + 1) == 2")
        self.assertEqual(g[0], "U")
        h = parse_ltl_text("(x + 1) * 2 == 4")
        self.assertEqual(h[0], "atom")


def _atomize(f):
    names = {}

    def go(g):
        if g[0] == "atom":
            n = g[1].name
            names.setdefault(n, len(names))
            return ("ap", names[n])
        if g[0] in ("true", "false"):
            return g
        return (g[0],) + tuple(go(x) for x in g[1:])
    return go(f)


if __name__ == "__main__":
    unittest.main()
