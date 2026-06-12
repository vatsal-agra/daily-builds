"""AST and recursive-descent parser for the RegexLab pattern syntax.

Supported syntax: literals, ``.``, escapes, character classes with ranges and
negation, quantifiers ``* + ? {m} {m,} {m,n}`` (greedy and lazy), alternation,
capturing ``( )`` and non-capturing ``(?: )`` groups, anchors ``^ $`` and word
boundaries ``\\b \\B``.  Predefined classes use ASCII semantics (``re.ASCII``).
Backreferences are deliberately unsupported: RegexLab is strictly regular.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from .lexer import Scanner, RegexSyntaxError  # noqa: F401  (re-exported)

MAX_CODEPOINT = 0x10FFFF
MAX_REPEAT = 1000

# ASCII-semantics predefined classes, as sorted disjoint (lo, hi) ranges.
DIGIT = ((48, 57),)
WORD = ((48, 57), (65, 90), (95, 95), (97, 122))
SPACE = ((9, 13), (32, 32))


# --------------------------------------------------------------------------- AST

@dataclass(frozen=True)
class Lit:
    ch: str

    def ranges(self):
        cp = ord(self.ch)
        return ((cp, cp),)


@dataclass(frozen=True)
class CharClass:
    ranges_raw: Tuple[Tuple[int, int], ...]  # possibly overlapping, unsorted
    negated: bool
    label: str  # original source text, for display

    def ranges(self):
        merged = _normalize(self.ranges_raw)
        if self.negated:
            merged = _complement(merged)
        return merged


@dataclass(frozen=True)
class Dot:
    def ranges(self):
        # Like re: any character except newline.
        return _complement(((10, 10),))


@dataclass(frozen=True)
class Anchor:
    kind: str  # '^', '$', 'b', 'B'


@dataclass(frozen=True)
class Concat:
    parts: tuple


@dataclass(frozen=True)
class Alt:
    branches: tuple


@dataclass(frozen=True)
class Repeat:
    child: object
    lo: int
    hi: Optional[int]  # None = unbounded
    lazy: bool


@dataclass(frozen=True)
class Group:
    child: object
    index: Optional[int]  # None = non-capturing


def _normalize(ranges):
    """Sort and merge possibly-overlapping ranges into disjoint sorted ranges."""
    if not ranges:
        return ()
    rs = sorted(ranges)
    out = [list(rs[0])]
    for lo, hi in rs[1:]:
        if lo <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return tuple((lo, hi) for lo, hi in out)


def _complement(ranges):
    """Complement of disjoint sorted ranges over [0, MAX_CODEPOINT]."""
    out = []
    prev = 0
    for lo, hi in ranges:
        if lo > prev:
            out.append((prev, lo - 1))
        prev = hi + 1
    if prev <= MAX_CODEPOINT:
        out.append((prev, MAX_CODEPOINT))
    return tuple(out)


# ------------------------------------------------------------------------ parser

class Parser:
    def __init__(self, pattern):
        self.s = Scanner(pattern)
        self.ngroups = 0

    def parse(self):
        ast = self._alt()
        if not self.s.eof():
            # The only way _alt stops early is an unmatched ')'.
            self.s.error("unbalanced parenthesis")
        return ast

    def _alt(self):
        branches = [self._concat()]
        while self.s.accept("|"):
            branches.append(self._concat())
        if len(branches) == 1:
            return branches[0]
        return Alt(tuple(branches))

    def _concat(self):
        parts = []
        while not self.s.eof() and self.s.peek() not in "|)":
            parts.append(self._repeat())
        if len(parts) == 1:
            return parts[0]
        return Concat(tuple(parts))

    def _repeat(self):
        start = self.s.pos
        atom = self._atom()
        quant = self._try_quantifier()
        if quant is None:
            return atom
        if isinstance(atom, Anchor):
            self.s.error("nothing to repeat", start)
        lo, hi, lazy = quant
        node = Repeat(atom, lo, hi, lazy)
        # A second quantifier directly after the first is an error, as in re.
        if self._try_quantifier() is not None:
            self.s.error("multiple repeat", start)
        return node

    def _try_quantifier(self):
        ch = self.s.peek()
        if ch == "*":
            self.s.next()
            return (0, None, self.s.accept("?"))
        if ch == "+":
            self.s.next()
            return (1, None, self.s.accept("?"))
        if ch == "?":
            self.s.next()
            return (0, 1, self.s.accept("?"))
        if ch == "{":
            spec = self._try_braces()
            if spec is not None:
                lo, hi = spec
                return (lo, hi, self.s.accept("?"))
        return None

    def _try_braces(self):
        """Parse {m} {m,} {m,n} after '{'. Returns (lo, hi) or None if the
        brace is not a valid quantifier (then it is a literal, as in re)."""
        save = self.s.pos
        self.s.next()  # consume '{'
        lo_digits = self._digits()
        comma = self.s.accept(",")
        hi_digits = self._digits() if comma else lo_digits
        closed = self.s.accept("}")
        # Not a quantifier (literal '{', as in re): '{x', '{}', '{,}', '{2', …
        if not closed or (not lo_digits and not hi_digits):
            self.s.pos = save
            return None
        lo = int(lo_digits) if lo_digits else 0
        hi = None if (comma and not hi_digits) else int(hi_digits)
        if hi is not None and hi < lo:
            self.s.error("min repeat greater than max repeat", save)
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            self.s.error(f"repeat count above limit ({MAX_REPEAT})", save)
        return (lo, hi)

    def _digits(self):
        out = []
        while self.s.peek().isdigit():
            out.append(self.s.next())
        return "".join(out)

    def _atom(self):
        ch = self.s.peek()
        if ch == "(":
            return self._group()
        if ch == "[":
            return self._class()
        if ch == ".":
            self.s.next()
            return Dot()
        if ch == "^":
            self.s.next()
            return Anchor("^")
        if ch == "$":
            self.s.next()
            return Anchor("$")
        if ch == "\\":
            return self._escape_atom()
        if ch in "*+?":
            self.s.error("nothing to repeat")
        if ch == "{":
            # '{' that is not a valid quantifier is a literal.
            spec_probe = self._try_braces()
            if spec_probe is not None:
                self.s.error("nothing to repeat")
            self.s.next()
            return Lit("{")
        return Lit(self.s.next())

    def _group(self):
        start = self.s.pos
        self.s.next()  # '('
        index = None
        if self.s.peek() == "?":
            if self.s.peek(1) == ":":
                self.s.next()
                self.s.next()
            else:
                self.s.error(
                    f"unsupported group extension '(?{self.s.peek(1)}'", start)
        else:
            self.ngroups += 1
            index = self.ngroups
        child = self._alt()
        if not self.s.accept(")"):
            self.s.error("missing ), unterminated group", start)
        return Group(child, index)

    def _escape_atom(self):
        start = self.s.pos
        self.s.next()  # '\'
        if self.s.eof():
            self.s.error("pattern ends with a bare backslash", start)
        ch = self.s.next()
        if ch == "b":
            return Anchor("b")
        if ch == "B":
            return Anchor("B")
        kind, value = self._escape_common(ch, start, in_class=False)
        if kind == "lit":
            return Lit(value)
        return CharClass(value, negated=(kind == "negclass"), label="\\" + ch)

    def _escape_common(self, ch, start, in_class):
        """Escapes valid both inside and outside classes.
        Returns ('lit', char) or ('class', ranges)."""
        simple = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v",
                  "a": "\a", "0": "\0"}
        if ch in simple:
            return ("lit", simple[ch])
        if ch == "x":
            h = self.s.peek() + self.s.peek(1)
            if len(h) == 2 and all(c in "0123456789abcdefABCDEF" for c in h):
                self.s.next()
                self.s.next()
                return ("lit", chr(int(h, 16)))
            self.s.error("incomplete \\x escape (expected two hex digits)", start)
        if ch == "d":
            return ("class", DIGIT)
        if ch == "D":
            return ("class", _complement(DIGIT)) if in_class else \
                   ("negclass", DIGIT)
        if ch == "w":
            return ("class", WORD)
        if ch == "W":
            return ("class", _complement(WORD)) if in_class else \
                   ("negclass", WORD)
        if ch == "s":
            return ("class", SPACE)
        if ch == "S":
            return ("class", _complement(SPACE)) if in_class else \
                   ("negclass", SPACE)
        if ch.isdigit():
            self.s.error(
                "backreferences are not supported (RegexLab is strictly "
                "regular; they make matching NP-hard)", start)
        if ch.isalnum():
            self.s.error(f"bad escape \\{ch}", start)
        return ("lit", ch)

    def _class(self):
        start = self.s.pos
        self.s.next()  # '['
        negated = self.s.accept("^")
        items = []
        if self.s.peek() == "]":
            # As in re: ']' cannot be the first member; '[]' is an error.
            self.s.error("unterminated character set (empty set?)", start)
        while True:
            if self.s.eof():
                self.s.error("unterminated character set", start)
            if self.s.peek() == "]":
                self.s.next()
                break
            items.extend(self._class_item(start))
        label = self.s.text[start:self.s.pos]
        return CharClass(tuple(items), negated, label)

    def _class_item(self, class_start):
        lo = self._class_char()
        if lo is None:  # a predefined class like \d — no ranges allowed off it
            return self._last_class_ranges
        if self.s.peek() == "-" and self.s.peek(1) not in ("]", ""):
            dash_pos = self.s.pos
            self.s.next()
            hi = self._class_char()
            if hi is None:
                self.s.error("bad character range (class after '-')", dash_pos)
            if ord(hi) < ord(lo):
                self.s.error(
                    f"bad character range {lo!r}-{hi!r} (reversed)", dash_pos)
            return [(ord(lo), ord(hi))]
        return [(ord(lo), ord(lo))]

    def _class_char(self):
        """One class member. Returns a char, or None if it was a predefined
        class escape (ranges left in self._last_class_ranges)."""
        ch = self.s.next()
        if ch != "\\":
            return ch
        start = self.s.pos - 1
        if self.s.eof():
            self.s.error("pattern ends with a bare backslash", start)
        esc = self.s.next()
        if esc == "b":  # inside a class, \b is backspace (as in re)
            return "\x08"
        kind, value = self._escape_common(esc, start, in_class=True)
        if kind == "lit":
            return value
        self._last_class_ranges = list(value)
        return None


def parse(pattern):
    """Parse a pattern; returns (ast, number_of_capturing_groups)."""
    p = Parser(pattern)
    ast = p.parse()
    return ast, p.ngroups
