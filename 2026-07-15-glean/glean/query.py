"""A small boolean/phrase/proximity query language, compiled to postings-list
set algebra and positional intersection over an InvertedIndex.

Grammar (flat, left-associative; explicit AND/OR bind adjacent clauses;
an operator-less gap between two clauses defaults to OR):

    expr    := unary ( (AND | OR | <nothing>) unary )*
    unary   := NOT unary | primary
    primary := '(' expr ')' | PHRASE | WORD [ NEAR/<k> (WORD | PHRASE) ]

Bare words and phrase text are stemmed with the same Porter pipeline used
at index time, so query terms always match on the same normalized form.
"""

import re

from . import tokenizer
from .tokenizer import porter_stem

_LEX_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()]+')
_NEAR_RE = re.compile(r"(?i)^near/(\d+)$")


class QuerySyntaxError(ValueError):
    pass


class _Tok:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"_Tok({self.kind!r}, {self.value!r})"


def _lex(query):
    toks = []
    for raw in _LEX_RE.findall(query):
        if raw == "(":
            toks.append(_Tok("LPAREN", raw))
        elif raw == ")":
            toks.append(_Tok("RPAREN", raw))
        elif raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            toks.append(_Tok("PHRASE", raw[1:-1]))
        elif raw.upper() == "AND":
            toks.append(_Tok("AND", raw))
        elif raw.upper() == "OR":
            toks.append(_Tok("OR", raw))
        elif raw.upper() == "NOT":
            toks.append(_Tok("NOT", raw))
        else:
            m = _NEAR_RE.match(raw)
            if m:
                toks.append(_Tok("NEAR", int(m.group(1))))
            else:
                toks.append(_Tok("WORD", raw))
    return toks


def _stem_phrase(text):
    words = [w for w, _s, _e in tokenizer.tokenize(text)]
    return [porter_stem(w) if w.isalpha() else w for w in words]


class TermNode:
    def __init__(self, raw):
        self.raw = raw
        self.stem = porter_stem(raw.lower()) if raw.isalpha() else raw.lower()

    def match(self, index):
        return set(index.postings.get(self.stem, {}).keys())

    def terms(self):
        return [self.stem]

    def __repr__(self):
        return f"Term({self.raw!r})"


class PhraseNode:
    def __init__(self, text):
        self.text = text
        self.stems = _stem_phrase(text)

    def match(self, index):
        if not self.stems:
            return set()
        candidate_sets = [set(index.postings.get(s, {}).keys()) for s in self.stems]
        candidates = set.intersection(*candidate_sets) if candidate_sets else set()
        return {d for d in candidates if index.phrase_positions(d, self.stems)}

    def terms(self):
        return list(self.stems)

    def __repr__(self):
        return f"Phrase({self.text!r})"


class NearNode:
    def __init__(self, left, right, k):
        self.left = left
        self.right = right
        self.k = k

    def match(self, index):
        left_docs = self.left.match(index)
        right_docs = self.right.match(index)
        candidates = left_docs & right_docs
        result = set()
        for doc_id in candidates:
            best = None
            for lt in self.left.terms():
                for rt in self.right.terms():
                    d = index.min_distance(doc_id, lt, rt)
                    if d is not None and (best is None or d < best):
                        best = d
            if best is not None and best <= self.k:
                result.add(doc_id)
        return result

    def terms(self):
        return self.left.terms() + self.right.terms()

    def __repr__(self):
        return f"Near({self.left!r}, {self.right!r}, {self.k})"


class AndNode:
    def __init__(self, left, right):
        self.left, self.right = left, right

    def match(self, index):
        return self.left.match(index) & self.right.match(index)

    def terms(self):
        return self.left.terms() + self.right.terms()


class OrNode:
    def __init__(self, left, right):
        self.left, self.right = left, right

    def match(self, index):
        return self.left.match(index) | self.right.match(index)

    def terms(self):
        return self.left.terms() + self.right.terms()


class NotNode:
    def __init__(self, node):
        self.node = node

    def match(self, index):
        return set(index.documents.keys()) - self.node.match(index)

    def terms(self):
        return []


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def advance(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t is None or t.kind != kind:
            got = t.kind if t else "end of query"
            raise QuerySyntaxError(f"expected {kind}, got {got}")
        return t

    def parse(self):
        if not self.toks:
            raise QuerySyntaxError("empty query")
        node = self.parse_expr()
        if self.peek() is not None:
            raise QuerySyntaxError(f"unexpected token {self.peek().value!r}")
        return node

    def parse_expr(self):
        node = self.parse_unary()
        while True:
            t = self.peek()
            if t is None or t.kind == "RPAREN":
                break
            if t.kind == "AND":
                self.advance()
                node = AndNode(node, self.parse_unary())
            elif t.kind == "OR":
                self.advance()
                node = OrNode(node, self.parse_unary())
            elif t.kind == "NOT":
                # an unmarked gap before NOT reads as exclusion ("a NOT b" == "a AND NOT b"),
                # matching how search boxes normally treat a trailing "-term".
                node = AndNode(node, self.parse_unary())
            elif t.kind in ("WORD", "PHRASE", "LPAREN"):
                node = OrNode(node, self.parse_unary())
            else:
                raise QuerySyntaxError(f"unexpected token {t.value!r}")
        return node

    def parse_unary(self):
        t = self.peek()
        if t is None:
            raise QuerySyntaxError("unexpected end of query")
        if t.kind == "NOT":
            self.advance()
            return NotNode(self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.advance()
        if t is None:
            raise QuerySyntaxError("unexpected end of query")
        if t.kind == "LPAREN":
            node = self.parse_expr()
            self.expect("RPAREN")
            return node
        if t.kind == "PHRASE":
            if not t.value.strip():
                raise QuerySyntaxError("empty phrase")
            return PhraseNode(t.value)
        if t.kind == "WORD":
            left = TermNode(t.value)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "NEAR":
                self.advance()
                k = nxt.value
                rhs = self.advance()
                if rhs is None or rhs.kind not in ("WORD", "PHRASE"):
                    raise QuerySyntaxError("NEAR requires a term on both sides")
                right_node = TermNode(rhs.value) if rhs.kind == "WORD" else PhraseNode(rhs.value)
                return NearNode(left, right_node, k)
            return left
        raise QuerySyntaxError(f"unexpected token {t.value!r}")


def parse(query_string):
    """Parse a query string into an AST. Raises QuerySyntaxError on bad input."""
    if not query_string or not query_string.strip():
        raise QuerySyntaxError("empty query")
    toks = _lex(query_string)
    return _Parser(toks).parse()


def positive_terms(node):
    """Stemmed terms contributing to relevance scoring (NOT subtrees excluded)."""
    return node.terms()
