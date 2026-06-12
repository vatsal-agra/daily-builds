import unittest

from rxlab import parser as P
from rxlab.lexer import RegexSyntaxError


def parse(pattern):
    return P.parse(pattern)[0]


class TestAst(unittest.TestCase):
    def test_literal_concat(self):
        ast = parse("ab")
        self.assertIsInstance(ast, P.Concat)
        self.assertEqual([n.ch for n in ast.parts], ["a", "b"])

    def test_alternation_and_groups(self):
        ast, ngroups = P.parse("(a|b)|(?:c)")
        self.assertIsInstance(ast, P.Alt)
        self.assertEqual(ngroups, 1)
        self.assertIsInstance(ast.branches[0], P.Group)
        self.assertEqual(ast.branches[0].index, 1)
        # non-capturing group is transparent in the AST
        self.assertIsInstance(ast.branches[1], P.Lit)

    def test_group_numbering_is_by_open_paren(self):
        _, ngroups = P.parse("((a)(b))(c)")
        self.assertEqual(ngroups, 4)

    def test_quantifiers(self):
        for pat, lo, hi, lazy in [
            ("a*", 0, None, False), ("a+?", 1, None, True),
            ("a?", 0, 1, False), ("a{3}", 3, 3, False),
            ("a{2,}", 2, None, False), ("a{2,5}?", 2, 5, True),
            ("a{,4}", 0, 4, False),
        ]:
            ast = parse(pat)
            self.assertIsInstance(ast, P.Repeat, pat)
            self.assertEqual((ast.lo, ast.hi, ast.lazy), (lo, hi, lazy), pat)

    def test_brace_literals(self):
        # invalid quantifier braces are literal text, as in re
        for pat, expect in [("a{", "a{"), ("a{}", "a{}"), ("a{,}", "a{,}"),
                            ("a{2", "a{2"), ("a{x}", "a{x}")]:
            import rxlab
            self.assertIsNotNone(rxlab.compile(pat).fullmatch(expect), pat)

    def test_class_ranges(self):
        ast = parse("[a-cx]")
        self.assertEqual(ast.ranges(), ((97, 99), (120, 120)))
        ast = parse("[^a]")
        rs = ast.ranges()
        self.assertEqual(rs[0], (0, 96))
        self.assertEqual(rs[-1], (98, 0x10FFFF))

    def test_dot_excludes_newline(self):
        rs = parse(".").ranges()
        self.assertNotIn(10, [cp for lo, hi in rs for cp in (lo, hi)
                              if lo <= 10 <= hi])

    def test_escapes(self):
        self.assertEqual(parse(r"\n").ch, "\n")
        self.assertEqual(parse(r"\x41").ch, "A")
        self.assertEqual(parse(r"\.").ch, ".")
        self.assertEqual(parse(r"\d").ranges(), ((48, 57),))

    def test_anchor_kinds(self):
        for pat, kind in [("^", "^"), ("$", "$"), (r"\b", "b"), (r"\B", "B")]:
            self.assertEqual(parse(pat).kind, kind)

    def test_backspace_in_class(self):
        self.assertEqual(parse(r"[\b]").ranges(), ((8, 8),))


class TestErrors(unittest.TestCase):
    BAD = ["a{2,1}", "(?P<n>a)", "(?=a)", "(a", "a)", "[z-a]", r"\x1",
           "a**", "*a", "^*", r"\q", r"\1", "[", "[]", "(?", "a\\",
           r"[\d-x]", r"[x-\d]", "a{1001}", "+"]

    def test_all_raise_with_position(self):
        for pat in self.BAD:
            with self.assertRaises(RegexSyntaxError, msg=pat) as cm:
                P.parse(pat)
            self.assertIsInstance(cm.exception.pos, int, pat)

    def test_messages_are_specific(self):
        cases = {
            r"\1": "backreferences",
            "(?=a)": "strictly regular",
            "(?": "unexpected end",
            "a**": "multiple repeat",
            "*": "nothing to repeat",
        }
        for pat, needle in cases.items():
            with self.assertRaises(RegexSyntaxError) as cm:
                P.parse(pat)
            self.assertIn(needle, str(cm.exception), pat)

    def test_ok_oddballs(self):
        # these are all valid, as in re
        for pat in ["[-a]", "[a-]", r"[\]]", r"[\d-]", "a{,3}", "x|", "(?:)",
                    "[{}]", "}"]:
            P.parse(pat)  # must not raise
