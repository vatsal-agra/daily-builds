import re
import time
import unittest

import rxlab


def spans(pat, text, mode="search"):
    m = getattr(rxlab.compile(pat), mode)(text)
    return None if m is None else (m.span(), m.groups())


def re_spans(pat, text, mode="search"):
    m = getattr(re.compile(pat, re.ASCII), mode)(text)
    return None if m is None else (m.span(), m.groups())


class TestSemantics(unittest.TestCase):
    CASES = [
        (r"a(b|c)*d", "abcbcd"), (r"a(b|c)*d", "ad"),
        (r"(\d+)-(\d+)", "call 555-1234 now"),
        (r"a*?b", "aaab"), (r"a*", "aaa"), (r"a*?", "aaa"),
        (r"(a+)(a*)", "aaaa"), (r"(a*)(a+)", "aaaa"),
        (r"^\w+@\w+\.\w+$", "me@example.com"),
        (r"\bcat\b", "the cat sat"), (r"\bcat\b", "concatenate"),
        (r"x{2,4}", "xxxxx"), (r"x{2,4}?", "xxxxx"),
        (r"(a)(b)?", "a"), (r"(a(b)?)+", "aba"),
        (r"(?:ab)+", "ababab"), (r"[^a-z]+", "abc123def"),
        (r"a$", "ba"), (r"^", ""), (r"x|", "y"), (r"", "anything"),
        (r"\B", ""), (r"\B", " "), (r"colou?r", "my colour"),
    ]

    def test_parity_with_re_all_modes(self):
        for pat, text in self.CASES:
            for mode in ("search", "match", "fullmatch"):
                self.assertEqual(spans(pat, text, mode),
                                 re_spans(pat, text, mode),
                                 f"{mode} {pat!r} on {text!r}")

    def test_pos_parameter(self):
        for pat, text, pos in [("^a", "ba", 1), (r"\bb", "ab cd", 1),
                               ("a", "bba", 1)]:
            mine = rxlab.compile(pat).search(text, pos)
            ref = re.compile(pat, re.ASCII).search(text, pos)
            self.assertEqual(mine.span() if mine else None,
                             ref.span() if ref else None, (pat, text, pos))

    def test_finditer_must_advance_rule(self):
        for pat, text in [(r"a*", "baa"), (r"b*", "ab"), (r"(?:\w)*?", "a1"),
                          (r"a??", "bb"), (r"(?:b)*?", "abb"), ("", "xy")]:
            self.assertEqual(
                [m.span() for m in rxlab.compile(pat).finditer(text)],
                [m.span() for m in re.finditer(pat, text, re.ASCII)],
                f"{pat!r} on {text!r}")

    def test_findall_group_shapes(self):
        for pat, text in [(r"\d+", "a1b22"), (r"(a)(b)?", "ab a"),
                          (r"(x)", "xx"), (r"a*", "baa")]:
            self.assertEqual(rxlab.compile(pat).findall(text),
                             re.findall(pat, text, re.ASCII))

    def test_unicode(self):
        m = rxlab.compile("[α-ω]+").search("τὰ ζῷα")
        self.assertEqual(m.group(), "τ")
        self.assertEqual(rxlab.compile(".").search("🎉x").group(), "🎉")

    def test_match_object_api(self):
        m = rxlab.compile(r"(\w+) (\w+)").match("hello world!")
        self.assertEqual(m.group(), "hello world")
        self.assertEqual(m.group(1, 2), ("hello", "world"))
        self.assertEqual(m.groups(), ("hello", "world"))
        self.assertEqual(m.span(2), (6, 11))
        self.assertEqual((m.start(), m.end()), (0, 11))
        with self.assertRaises(IndexError):
            m.group(3)
        m2 = rxlab.compile(r"(a)|(b)").match("a")
        self.assertEqual(m2.groups(), ("a", None))
        self.assertEqual(m2.groups(default=""), ("a", ""))
        self.assertEqual(m2.span(2), (-1, -1))

    def test_last_iteration_capture(self):
        # group keeps its value from an earlier iteration, as in re
        self.assertEqual(rxlab.compile(r"(a(b)?)+").match("aba").group(2),
                         re.match(r"(a(b)?)+", "aba").group(2))


class TestNoBacktrackingBlowup(unittest.TestCase):
    def test_redos_pattern_is_fast(self):
        t0 = time.time()
        m = rxlab.compile(r"(a+)+$").search("a" * 60 + "X")
        elapsed = time.time() - t0
        self.assertIsNone(m)
        self.assertLess(elapsed, 1.0,
                        "Pike VM must not backtrack exponentially")

    def test_program_size_cap(self):
        with self.assertRaises(rxlab.RegexCompileError):
            rxlab.compile("(?:" + "a{100}" * 5 + "){100}")
