import itertools
import time
import unittest
from tests.helpers import *  # noqa
from parsimony.lr import ParseError


def catalan(n):
    from math import comb
    return comb(2 * n, n) // (n + 1)


class Earley(unittest.TestCase):
    def test_catalan_counts(self):
        L = example("ambiguous.pg")
        for k in range(1, 10):                              # k operands → Catalan(k-1) parses
            self.assertEqual(L.earley("+".join("n" * 1 for _ in range(k))).count(), catalan(k - 1), k)

    def test_enumeration_distinct_and_complete(self):
        r = example("ambiguous.pg").earley("n+n+n+n")
        trees = r.trees(100)
        self.assertEqual(len(trees), 5)
        self.assertEqual(len({t.sexp() for t in trees}), 5)
        self.assertEqual(len(r.trees(3)), 3)

    def test_ambiguity_report(self):
        amb = example("ambiguous.pg").earley("n+n+n").ambiguities()
        self.assertEqual(len(amb), 1)
        self.assertIn("2 different ways", amb[0])
        self.assertEqual(example("json.pg").earley('[1, {"a": null}]').ambiguities(), [])

    def test_unambiguous_json(self):
        r = example("json.pg").earley('{"a": [1, 2, {"b": null}], "c": true}')
        self.assertEqual(r.count(), 1)
        self.assertEqual(r.trees(1)[0], example("json.pg").parse('{"a": [1, 2, {"b": null}], "c": true}'))

    def test_epsilon_and_nullable_chains(self):
        L = Language("%skip /[ ]+/\nS : A A 'x' ; A : B | ; B : ;")
        r = L.earley("x")
        self.assertEqual(r.count(), 4)                       # each A: via B or directly empty
        self.assertEqual(len({t.sexp() for t in r.trees(10)}), 4)

    def test_infinite_ambiguity(self):
        r = example("nullable.pg").earley("a")
        self.assertEqual(r.count(), float("inf"))
        self.assertGreater(len(r.trees(6)), 3)               # finite sample of an infinite forest
        self.assertEqual(example("nullable.pg").earley("").count(), float("inf"))

    def test_cycle_a_derives_a(self):
        L = Language("S : S | 'a' ;")
        self.assertEqual(L.earley("a").count(), float("inf"))
        self.assertEqual(L.analysis.cyclic(), [["S"]])

    def test_left_right_and_hidden_recursion(self):
        for src in ("S : S 'a' | 'a' ;", "S : 'a' S | 'a' ;", "S : 'a'+ ;"):
            L = Language("%skip /[ ]+/\n" + src)
            self.assertEqual(L.earley("a a a a").count(), 1, src)

    def test_syntax_errors(self):
        L = example("json.pg")
        for bad in ('{"a" 1}', "[1,", "{", ""):
            with self.subTest(bad=bad), self.assertRaises(ParseError):
                L.earley(bad)
        with self.assertRaises(ParseError) as cm:
            L.earley('{"a" 1}')
        self.assertEqual(cm.exception.expected, ["':'"])

    def test_non_lr_grammar_palindromes(self):
        # Even palindromes over {a,b}: deterministic-impossible (needs guessing the middle) → not LR(k)
        L = Language("%skip /[ ]+/\nP : 'a' P 'a' | 'b' P 'b' | ;")
        self.assertFalse(any(not L.table(m).conflicts for m in ("lr0", "slr", "lalr", "lr1")))
        for s in ["", "a a", "a b b a", "b a a b"]:
            self.assertEqual(L.earley(s).count(), 1, s)
        for s in ["a", "a b", "a b a b"]:
            with self.assertRaises(ParseError):
                L.earley(s)

    def test_agrees_with_lalr_on_trees(self):
        L = example("ll1_lists.pg")
        src = "x = 1 + 2 * (y - 3); print x / 4; z = ((7));"
        self.assertEqual(L.earley(src).trees(1)[0], L.parse(src, "lalr"))

    def test_scales_to_deep_inputs(self):                    # REVIEW #6/#7/#8
        L = Language("%token N /[0-9]+/\n%skip /\\s+/\ne : e '+' N | N ;")
        t0 = time.time()
        r = L.earley(" + ".join(["1"] * 20000))
        self.assertEqual(r.count(), 1)
        tree = r.trees(1)[0]
        self.assertEqual(len(tree.text().split()), 39999)
        self.assertLess(time.time() - t0, 20)


if __name__ == "__main__":
    unittest.main()
