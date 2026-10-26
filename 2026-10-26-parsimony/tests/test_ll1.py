import itertools
import unittest
from tests.helpers import *  # noqa
from parsimony import GrammarError
from parsimony.analysis import Analysis
from parsimony.ll1 import build_ll1
from parsimony.lr import ParseError
from parsimony.transform import make_ll1_friendly


class LL1(unittest.TestCase):
    def test_ll1_table_conflict_free(self):
        L = example("ll1_lists.pg").ll1_language()
        t = build_ll1(L.grammar, L.analysis)
        self.assertEqual(t.conflicts, [])
        self.assertIn("LL(1): no conflicts", t.dump())

    def test_left_recursion_conflicts_with_hint(self):
        L = Language("e : e '+' 'n' | 'n' ;")
        t = build_ll1(L.grammar, L.analysis)
        self.assertEqual({c.kind for c in t.conflicts}, {"FIRST/FIRST"})
        self.assertIn("transform", t.dump())
        with self.assertRaises(GrammarError):
            L.parse("n+n", "ll1")

    def test_first_follow_conflict_kind(self):
        L = Language("S : A 'a' ; A : 'a' | ;")
        self.assertEqual([c.kind for c in build_ll1(L.grammar, L.analysis).conflicts], ["FIRST/FOLLOW"])

    def test_tree_equals_lalr_tree(self):
        L = example("ll1_lists.pg")
        for src in ["", "x = 1;", "print (1 + 2) * x;", "a = b - c - d; print a / 2 * 3;"]:
            self.assertEqual(L.parse(src, "ll1"), L.parse(src, "lalr"), src)
            self.assertEqual(L.parse(src, "ll1"), L.parse(src, "earley"), src)   # REVIEW #12 ordering

    def test_ll1_errors(self):
        L = example("ll1_lists.pg")
        with self.assertRaises(ParseError) as cm:
            L.parse("x = ;", "ll1")
        self.assertEqual((cm.exception.token.line, cm.exception.token.col), (1, 5))
        self.assertIn("expected one of", str(cm.exception))
        with self.assertRaises(ParseError):
            L.parse("x = 1", "ll1")                      # missing ';' at EOF

    def test_trace(self):
        rows = []
        example("ll1_lists.pg").parse("x=1;", "ll1", rows)
        acts = [r.action.split()[0] for r in rows]
        self.assertEqual(acts[0], "predict")
        self.assertIn("match", acts)
        self.assertTrue(rows[0].stack.startswith("prog"))


class Transform(unittest.TestCase):
    def accepts_all(self, a, b, alphabet, maxlen):
        La, Lb = Language(a), Language(b)
        for n in range(maxlen + 1):
            for w in itertools.product(alphabet, repeat=n):
                s = " ".join(w)
                ra = rb = True
                try: La.earley(s)
                except ParseError: ra = False
                try: Lb.earley(s)
                except ParseError: rb = False
                self.assertEqual(ra, rb, s)

    def test_direct_left_recursion(self):
        src = "%skip /[ ]+/\ne : e '+' t | t ; t : t '*' f | f ; f : '(' e ')' | 'n' ;"
        L = Language(src)
        g2, log = make_ll1_friendly(L.grammar)
        self.assertTrue(any("e_tail" in l for l in log))
        self.assertEqual(build_ll1(g2, Analysis(g2)).conflicts, [])
        # transformed grammar describes the same language
        self.accepts_all(src, g2.pretty(full=True), ["n", "+", "*", "(", ")"], 6)

    def test_indirect_left_recursion(self):
        src = "%skip /[ ]+/\nS : A 'a' | 'b' ; A : S 'c' | 'd' ;"
        g2, _ = make_ll1_friendly(Language(src).grammar)
        self.assertEqual(Analysis(g2).left_recursive(), [])
        # language preserved (the result is not claimed to be LL(1): S → b | b c … needs more factoring)
        self.accepts_all(src, g2.pretty(full=True), ["a", "b", "c", "d"], 6)

    def test_left_factoring(self):
        src = "%skip /[ ]+/\nS : 'i' 'c' 't' S | 'i' 'c' 't' S 'e' S | 'a' ;"
        g2, log = make_ll1_friendly(Language(src).grammar)
        self.assertTrue(any("left-factored" in l for l in log))
        self.assertEqual(Analysis(g2).left_recursive(), [])
        self.accepts_all(src, g2.pretty(full=True), ["i", "c", "t", "e", "a"], 6)

    def test_cyclic_grammar_refused(self):
        with self.assertRaises(GrammarError):
            make_ll1_friendly(Language("S : S | 'a' ;").grammar)

    def test_noop(self):
        _, log = make_ll1_friendly(example("ll1_lists.pg").ll1_language().grammar)
        self.assertIn("nothing to do", log[0])


if __name__ == "__main__":
    unittest.main()
