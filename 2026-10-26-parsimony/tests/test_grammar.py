import unittest
from tests.helpers import *  # noqa
from parsimony import GrammarError, Lexer, LexError, load_grammar
from parsimony.analysis import Analysis


class GrammarDSL(unittest.TestCase):
    def test_basic_rules_and_tokens(self):
        g = load_grammar("%token N /[0-9]+/\ne : e '+' N | N ;")
        self.assertEqual([str(p) for p in g.productions], ["e -> e '+' N", "e -> N"])
        self.assertEqual(g.terminals, ["N", "'+'"])
        self.assertEqual(g.start, "e")

    def test_ebnf_desugaring_is_hidden(self):
        g = load_grammar("s : 'a'* 'b'+ 'c'? ('d' | 'e') ;")
        self.assertEqual(len(g.hidden), 4)
        self.assertTrue(all(h.startswith("_") for h in g.hidden))
        lang = Language("%skip /[ ]+/\ns : 'a'* 'b'+ 'c'? ('d' | 'e') ;")
        t = lang.parse("a a b b c e")
        self.assertEqual([c.text for c in t.children], list("aabbce"))   # helpers spliced away

    def test_underscore_rules_are_hidden(self):
        L = Language("%skip /[ ]+/\ns : _pair+ ;\n_pair : 'a' 'b' ;")
        self.assertEqual([c.text for c in L.parse("a b a b").children], list("abab"))
        g = load_grammar("_grp1 : 'x' ;\ns : ('a'|'b') _grp1 ;")     # generated names avoid user names
        self.assertEqual(len(g.nonterminals), len(set(g.nonterminals)))

    def test_right_style_ebnf_is_ll_friendly(self):
        L = Language("%skip /[ ]+/\ns : 'a'* ;", "right")
        self.assertEqual(L.parse("a a a", "ll1").text(), "a a a")

    def test_precedence_levels(self):
        g = load_grammar("%left '+' '-'\n%right '^'\n%nonassoc '<'\ne : e '+' e | e '^' e | e '<' e | 'n' ;")
        self.assertEqual(g.precedence["'+'"], (1, "left"))
        self.assertEqual(g.precedence["'^'"], (2, "right"))
        self.assertEqual(g.precedence["'<'"], (3, "nonassoc"))
        self.assertEqual(g.productions[0].prec, (1, "left"))         # yacc: last terminal wins

    def test_prec_override_and_pseudo_token(self):
        g = load_grammar("%left '-'\n%right UMINUS\ne : e '-' e | '-' e %prec UMINUS | 'n' ;")
        self.assertEqual(g.productions[1].prec, (2, "right"))

    def test_regex_with_slash_in_class(self):               # REVIEW #1
        L = Language("%token P /[^/]+/\ns : P ;")
        self.assertEqual(L.parse("abc").children[0].text, "abc")
        L = Language("%token P /[]/]+/\ns : P ;")             # ']' first in a class is literal
        self.assertEqual(L.parse("]/]").children[0].text, "]/]")

    def test_comments_and_escapes(self):
        L = Language("# c\n// c2\n/* c3\n */ s : 'a\\'b' ; # tail")
        self.assertEqual(L.parse("a'b").children[0].type, "'a'b'")

    def test_error_reporting(self):
        bad = {
            "": "no rules",
            "%token A /a/": "no rules",
            "s : foo ;": "undefined symbol foo",
            "s : 'a'": "expected ;",
            "%start zz\ns : 'a' ;": "zz has no rules",
            "s : 'a' %prec Q ;": "no precedence declaration",
            "%token A /(/\ns : A ;": "bad regex",
            "%token A /a*/\ns : A ;": "empty string",
            "%token A /a/\n%token A /b/\ns : A ;": "twice",
            "s : 'a' ;\n%bogus": "unknown directive",
            "s : 'unterminated ;": "unterminated string",
            "s : 'a' ; @": "unexpected character",
            "%left\ns : 'a' ;": "at least one token",
            "%token A /a/\nA : 'x' ;": "both as token and rule",
        }
        for src, frag in bad.items():
            with self.subTest(src=src):
                with self.assertRaises(GrammarError) as cm:
                    load_grammar(src)
                self.assertIn(frag, str(cm.exception))

    def test_error_carries_line_number(self):
        with self.assertRaises(GrammarError) as cm:
            load_grammar("s : 'a' ;\n\nt : zzz ;")
        self.assertEqual(cm.exception.line, 3)


class LexerTests(unittest.TestCase):
    def setUp(self):
        self.g = load_grammar("%token ID /[a-z]+/\n%token NUM /[0-9]+/\n%skip /[ \\n]+/\ns : ID | NUM | 'if' | '<' | '<=' ;")
        self.lx = Lexer(self.g)

    def test_longest_match_and_keyword_priority(self):
        self.assertEqual([t.type for t in self.lx.tokenize("if iffy < <= 12")],
                         ["'if'", "ID", "'<'", "'<='", "NUM", "$end"])

    def test_positions(self):
        ts = self.lx.tokenize("ab\n  cd")
        self.assertEqual([(t.line, t.col) for t in ts[:2]], [(1, 1), (2, 3)])

    def test_unexpected_char(self):
        with self.assertRaises(LexError) as cm:
            self.lx.tokenize("ab\n  $")
        self.assertEqual((cm.exception.line, cm.exception.col), (2, 3))

    def test_empty_input(self):
        self.assertEqual([t.type for t in self.lx.tokenize("")], ["$end"])


class AnalysisTests(unittest.TestCase):
    def test_first_follow_nullable_textbook(self):
        # Dragon book grammar 4.28 (left-factored expression grammar)
        L = Language("""%token id /[a-z]/
        E : T Ep ; Ep : '+' T Ep | ; T : F Tp ; Tp : '*' F Tp | ; F : '(' E ')' | id ;""")
        a = L.analysis
        self.assertEqual(a.nullable, {"Ep", "Tp"})
        self.assertEqual(a.first["E"], {"'('", "id"})
        self.assertEqual(a.first["Ep"], {"'+'"})
        self.assertEqual(a.follow["E"], {"')'", "$end"})
        self.assertEqual(a.follow["Ep"], {"')'", "$end"})
        self.assertEqual(a.follow["T"], {"'+'", "')'", "$end"})
        self.assertEqual(a.follow["F"], {"'*'", "'+'", "')'", "$end"})

    def test_diagnostics(self):
        L = Language("%token U /u/\n%token X /x/\ns : s 'a' | 'a' | t ; t : t ; z : 'q' ; w : w 'b' ; s : 'a' ;")
        rep = L.analysis.report()
        self.assertRegex(rep, r"unreachable symbols: .*\bz\b.*\bw\b")
        self.assertIn("declared but unused tokens: U, X", rep)
        self.assertIn("duplicate production: s -> 'a'", rep)
        self.assertIn("cyclic derivation", rep)
        self.assertIn("non-productive nonterminals", rep)

    def test_ebnf_helper_recursion_is_not_reported(self):    # REVIEW #2
        rep = Language("s : 'a'* 'b'+ ;").analysis.report()
        self.assertNotIn("left recursion", rep)
        self.assertIn("diagnostics  : none", rep)

    def test_real_left_recursion_reported_with_hint(self):
        rep = Language("e : e '+' 'n' | 'n' ;").analysis.report()
        self.assertIn("left recursion: e", rep)
        self.assertIn("transform", rep)

    def test_shortest_derivations(self):
        a = Language("s : 'a' s 'b' | 'c' ;").analysis
        self.assertEqual(a.shortest()["s"], ["'c'"])



class RoundTrip(unittest.TestCase):
    def test_pretty_full_reloads_to_same_grammar(self):
        import glob, os
        for path in sorted(glob.glob(os.path.join(EX, "*.pg"))):
            with self.subTest(path=os.path.basename(path)):
                a = Language.from_file(path)
                b = Language(a.grammar.pretty(full=True))
                key = lambda g: sorted((p.lhs, p.rhs, p.prec) for p in g.productions)
                self.assertEqual(key(a.grammar), key(b.grammar))
                self.assertEqual(a.grammar.hidden, b.grammar.hidden)


if __name__ == "__main__":
    unittest.main()
