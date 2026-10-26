import random
import unittest
from tests.helpers import *  # noqa
from parsimony.lr import LRParser, ParseError, METHODS, build_table


def classes(L):
    return {m: not L.table(m).conflicts for m in METHODS}


class Classification(unittest.TestCase):
    """The textbook separating grammars must land in exactly the classes the literature says."""

    def test_slr_but_not_lr0(self):
        self.assertEqual(classes(example("json.pg")), dict(lr0=False, slr=True, lalr=True, lr1=True))

    def test_lalr_but_not_slr(self):                 # Dragon book 4.49
        self.assertEqual(classes(example("slr_fails.pg")), dict(lr0=False, slr=False, lalr=True, lr1=True))

    def test_lr1_but_not_lalr(self):                 # merged 'c' states → reduce/reduce
        L = example("lr1_not_lalr.pg")
        self.assertEqual(classes(L), dict(lr0=False, slr=False, lalr=False, lr1=True))
        self.assertTrue(all(c.kind == "reduce/reduce" for c in L.table("lalr").conflicts))
        self.assertEqual(L.table("lalr").n_states, 13)      # LALR keeps the LR(0) state count
        self.assertEqual(L.table("lr1").n_states, 14)

    def test_ambiguous_is_not_lr_at_all(self):
        for f in ("dangling_else.pg", "ambiguous.pg", "nullable.pg"):
            self.assertFalse(any(classes(example(f)).values()), f)

    def test_precedence_removes_dangling_else(self):
        L = example("dangling_else_fixed.pg")
        self.assertTrue(all(classes(L).values()))
        self.assertEqual(len(L.table("lalr").resolved), 1)
        t = L.parse("if a then if b then c else d")
        # 'else' binds to the nearest 'if'
        self.assertEqual(t.sexp(), "(stmt if ID:a then (stmt if ID:b then (stmt ID:c) else (stmt ID:d)))")

    def test_conflict_report_has_example_and_items(self):
        rep = example("dangling_else.pg").table("lalr").conflict_report()
        self.assertIn("shift/reduce on 'else'", rep)
        self.assertIn("after reading:  if ID then ID • else", rep)
        self.assertIn("stmt -> 'if' ID 'then' stmt • 'else' stmt", rep)

    def test_state_counts_known(self):
        self.assertEqual([example("slr_fails.pg").table(m).n_states for m in METHODS], [10, 10, 10, 14])


class Precedence(unittest.TestCase):
    def setUp(self):
        self.L = example("expr.pg")

    def ev(self, node):
        from parsimony.lexer import Token
        if isinstance(node, Token):
            return float(node.text)
        k = node.children
        if len(k) == 1:
            return self.ev(k[0])
        if len(k) == 2:                                  # unary minus
            return -self.ev(k[1])
        if isinstance(k[0], Token):                      # ( e )
            return self.ev(k[1])
        a, op, b = self.ev(k[0]), k[1].text, self.ev(k[2])
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        if op == "/": return a / b
        return a ** b

    def test_associativity_and_levels(self):
        for src, want in [("1-2-3", -4), ("2^3^2", 512), ("2+3*4", 14), ("(2+3)*4", 20), ("8/4/2", 1),
                          ("-2*3", -6), ("1+2*3^2", 19), ("2*3+4*5", 26)]:
            for m in METHODS:
                self.assertEqual(self.ev(self.L.parse(src, m)), want, (src, m))

    def test_random_expressions_match_python(self):
        rnd = random.Random(7)

        def gen(d):
            if d == 0 or rnd.random() < 0.25:
                return str(rnd.randint(1, 9))
            r = rnd.random()
            if r < 0.15:
                return "-" + gen(d - 1)
            if r < 0.3:
                return "(" + gen(d - 1) + ")"
            return gen(d - 1) + rnd.choice(["+", "-", "*"]) + gen(d - 1)
        for _ in range(300):
            src = gen(5)
            self.assertEqual(self.ev(self.L.parse(src)), eval(src), src)

    def test_nonassoc_makes_chains_an_error(self):
        L = Language("%token N /[0-9]+/\n%skip /[ ]+/\n%nonassoc '<'\ne : e '<' e | N ;")
        L.parse("1 < 2")
        with self.assertRaises(ParseError):
            L.parse("1 < 2 < 3")


class Driver(unittest.TestCase):
    def test_trace_shape(self):
        L = example("expr.pg")
        rows = []
        L.parse("1+2", "lalr", rows)
        self.assertEqual([r.action.split()[0] for r in rows],
                         ["shift", "reduce", "shift", "shift", "reduce", "reduce", "accept"])
        self.assertTrue(rows[-1].stack.endswith("expr 1"))

    def test_syntax_error_position_and_expected(self):
        L = example("expr.pg")
        with self.assertRaises(ParseError) as cm:
            L.parse("1 +\n  * 2")
        e = cm.exception
        self.assertEqual((e.token.line, e.token.col), (2, 3))
        self.assertEqual(e.expected, ["'('", "'-'", "NUM"])
        self.assertIn("2:3", str(e))

    def test_error_at_eof(self):
        with self.assertRaises(ParseError) as cm:
            example("expr.pg").parse("1 +")
        self.assertIn("end of input", str(cm.exception))

    def test_empty_input_and_nullable_start(self):
        self.assertEqual(Language("s : 'a'* ;").parse("").sexp(), "(s)")
        with self.assertRaises(ParseError):
            Language("s : 'a' ;").parse("")

    def test_deep_trees_do_not_overflow(self):                 # REVIEW #4/#5
        L = Language("%token N /[0-9]+/\n%skip /\\s+/\ne : e '+' N | N ;")
        t = L.parse(" + ".join(["1"] * 6000))
        self.assertEqual(t.compact().count() > 12000, True)
        self.assertEqual(t, L.parse(" + ".join(["1"] * 6000)))
        self.assertIn('"rule"', t.json())
        self.assertTrue(t.sexp().startswith("(e (e (e"))
        self.assertIn("├──", t.pretty())

    def test_json_and_sexp_formats(self):
        t = example("expr.pg").parse("1+2")
        j = t.to_json()
        self.assertEqual(j["rule"], "expr")
        self.assertEqual(j["children"][1], {"token": "'+'", "text": "+", "line": 1, "col": 2})


class Recovery(unittest.TestCase):
    def setUp(self):
        self.L = example("recover.pg")

    def run_(self, src):
        return LRParser(self.L.table("lalr")).parse_recovering(self.L.tokenize(src))

    def test_clean_input_has_no_errors(self):
        r = self.run_("a = 1; b = 2 * 3;")
        self.assertEqual(r.errors, [])
        self.assertEqual(len(r.tree.children), 2)

    def test_multiple_errors_reported_and_parse_continues(self):
        r = self.run_("a = 1; b = + ; c = (2 * ; d = 4 + 5;")
        self.assertEqual(len(r.errors), 2)
        self.assertEqual([(e.token.line, e.token.col) for e in r.errors], [(1, 12), (1, 25)])
        kinds = [c.children[0].type for c in r.tree.children]
        self.assertEqual(kinds, ["ID", "error", "error", "ID"])        # good, bad, bad, good

    def test_cascade_suppression(self):
        r = self.run_("a = 1 b = 2 c = 3;")
        self.assertEqual(len(r.errors), 1)

    def test_unrecoverable_at_eof(self):
        r = self.run_("a = 1; b = 3")
        self.assertIsNone(r.tree)
        self.assertEqual(len(r.errors), 1)

    def test_grammar_without_error_rules_cannot_recover(self):
        L = example("expr.pg")
        r = LRParser(L.table("lalr")).parse_recovering(L.tokenize("1 + * 2"))
        self.assertIsNone(r.tree)
        self.assertEqual(len(r.errors), 1)


if __name__ == "__main__":
    unittest.main()
