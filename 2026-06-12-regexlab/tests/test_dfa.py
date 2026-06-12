import itertools
import re
import unittest

import rxlab
from rxlab.dfa import DFA
from rxlab.lexer import RegexCompileError

PATTERNS = [
    "a", "ab", "a|b", "(a|b)*abb", "a*b+c?", "x{2,4}", "[a-f]+\\d?",
    "^ab$", "a$", "^a|b$", "(?:ab|a)*b", "colou?r", "(a|ab)(c|bcd)",
    ".", ".*", "(?:)", "^$", "a$b", "[^ab]+", "\\d{1,3}(?:\\.\\d{1,3}){3}",
]
TEXTS = ["", "a", "b", "ab", "abb", "aabb", "ababb", "ad", "abcd", "xxx",
         "xxxxx", "color", "colour", "abcbcd", "f3", "abcde", "1.2.3.4",
         "12.34.56.78", "zzz", "a b", "\n"]


def moore_minimize_count(d):
    """Independent Moore-style minimization (signature refinement) used to
    cross-check the Hopcroft implementation's state count."""
    n = len(d.trans)
    dead = n
    total = n + 1

    def delta(q, c):
        return dead if q == dead else d.trans[q].get(c, dead)

    block = [1 if (q < n and d.accept[q]) else 0 for q in range(total)]
    while True:
        sigs = {}
        new = []
        for q in range(total):
            sig = (block[q],) + tuple(block[delta(q, c)]
                                      for c in range(d.n_classes))
            new.append(sigs.setdefault(sig, len(sigs)))
        if new == block:
            break
        block = new
    # count blocks reachable from start without passing through dead's block
    dead_block = block[dead]
    seen, stack = set(), [block[0]]
    while stack:
        b = stack.pop()
        if b in seen:
            continue
        seen.add(b)
        rep = next(q for q in range(total) if block[q] == b and q != dead)
        for c in range(d.n_classes):
            tb = block[delta(rep, c)]
            if tb != dead_block:
                stack.append(tb)
    return len(seen)


class TestDFA(unittest.TestCase):
    def test_equivalence_with_nfa(self):
        for pat in PATTERNS:
            p = rxlab.compile(pat)
            d = p.dfa()
            for text in TEXTS:
                self.assertEqual(d.fullmatch(text),
                                 p.fullmatch(text) is not None,
                                 f"{pat!r} on {text!r}")

    def test_equivalence_with_re(self):
        for pat in PATTERNS:
            d = rxlab.compile(pat).dfa()
            ref = re.compile(pat, re.ASCII)
            for text in TEXTS:
                self.assertEqual(d.fullmatch(text),
                                 ref.fullmatch(text) is not None,
                                 f"{pat!r} on {text!r}")

    def test_textbook_minimization(self):
        # the classic example: (a|b)*abb has a 4-state minimal DFA
        d = rxlab.compile("(a|b)*abb").dfa()
        self.assertEqual(d.n_states, 4)
        self.assertLessEqual(d.n_states, d.n_subset)

    def test_hopcroft_agrees_with_moore(self):
        for pat in PATTERNS:
            unmin = rxlab.compile(pat).dfa(minimize=False)
            minned = rxlab.compile(pat).dfa(minimize=True)
            self.assertEqual(minned.n_states, moore_minimize_count(unmin),
                             f"minimal state count differs for {pat!r}")

    def test_minimized_no_larger(self):
        for pat in PATTERNS:
            d = rxlab.compile(pat).dfa()
            self.assertLessEqual(d.n_states, d.n_subset, pat)

    def test_word_boundary_rejected(self):
        with self.assertRaises(RegexCompileError) as cm:
            rxlab.compile(r"\bcat\b").dfa()
        self.assertIn("word boundaries", str(cm.exception))

    def test_unsatisfiable_pattern(self):
        d = rxlab.compile("a$b").dfa()
        for text in ["", "a", "ab", "a$b"]:
            self.assertFalse(d.fullmatch(text))
        self.assertEqual(d.n_states, 1)

    def test_exhaustive_small_alphabet(self):
        # every string over {a,b} up to length 5, several patterns
        for pat in ["(a|b)*abb", "a(?:ba)*b?", "(?:aa|bb)+", "a*b*a*"]:
            p = rxlab.compile(pat)
            d = p.dfa()
            for k in range(6):
                for tup in itertools.product("ab", repeat=k):
                    text = "".join(tup)
                    self.assertEqual(d.fullmatch(text),
                                     p.fullmatch(text) is not None,
                                     f"{pat!r} on {text!r}")

    def test_class_partition(self):
        d = rxlab.compile("[a-c][b-d]").dfa()
        # boundaries at a..d should split into classes; chars outside fail
        self.assertTrue(d.fullmatch("bc"))
        self.assertTrue(d.fullmatch("cd"))
        self.assertTrue(d.fullmatch("ad"))
        self.assertFalse(d.fullmatch("da"))
        self.assertFalse(d.fullmatch("ae"))
        self.assertEqual(d.class_of(ord("z")), -1)
