"""Query language: AND/OR/NOT boolean expressions, "phrase" queries via
positional adjacency, prefix* wildcards via a trie, and fuzzy~N matching via
a BK-tree. Parsing is recursive descent over a hand-rolled tokenizer.
"""

import re

from sift.analyzer import analyze, analyze_query_term
from sift.rank import bm25_term_score

_QUERY_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()]+')
_OPERATORS = {"and", "or", "not"}


class QueryError(ValueError):
    pass


class QueryContext:
    """Bundles the resources leaf nodes need to resolve against an index."""

    def __init__(self, index, trie=None, bktree=None, fuzzy_default=2, k1=1.5, b=0.75):
        self.index = index
        self.trie = trie
        self.bktree = bktree
        self.fuzzy_default = fuzzy_default
        self.k1 = k1
        self.b = b

    def all_doc_ids(self):
        return set(self.index.documents.keys())


# ---------------------------------------------------------------- AST nodes


class TermLeaf:
    def __init__(self, term):
        self.term = term

    def matched_docs(self, ctx):
        return set(ctx.index.postings.get(self.term, {}).keys())

    def score_in_doc(self, ctx, doc_id):
        tf = ctx.index.term_freq(self.term, doc_id)
        if tf == 0:
            return 0.0
        df = ctx.index.doc_freq(self.term)
        doc = ctx.index.documents[doc_id]
        return bm25_term_score(
            tf, df, doc.length, ctx.index.avg_doc_length, ctx.index.doc_count, ctx.k1, ctx.b
        )

    def __repr__(self):
        return f"Term({self.term!r})"


class PhraseLeaf:
    def __init__(self, offset_terms):
        # offset_terms: list of (relative_position_offset, term), offset 0-based
        # from the phrase's first *content* word.
        self.offset_terms = offset_terms

    def _candidate_docs(self, ctx):
        if not self.offset_terms:
            return set()
        term_sets = [
            set(ctx.index.postings.get(term, {}).keys()) for _, term in self.offset_terms
        ]
        result = term_sets[0]
        for s in term_sets[1:]:
            result = result & s
        return result

    def _occurrences_in_doc(self, ctx, doc_id):
        if not self.offset_terms:
            return 0
        first_offset, first_term = self.offset_terms[0]
        first_positions = ctx.index.postings[first_term][doc_id].positions
        count = 0
        for start in first_positions:
            base = start - first_offset
            ok = True
            for offset, term in self.offset_terms[1:]:
                bucket = ctx.index.postings.get(term, {}).get(doc_id)
                if bucket is None or (base + offset) not in bucket.positions:
                    ok = False
                    break
            if ok:
                count += 1
        return count

    def matched_docs(self, ctx):
        return {
            doc_id
            for doc_id in self._candidate_docs(ctx)
            if self._occurrences_in_doc(ctx, doc_id) > 0
        }

    def score_in_doc(self, ctx, doc_id):
        tf = self._occurrences_in_doc(ctx, doc_id)
        if tf == 0:
            return 0.0
        df = len(self.matched_docs(ctx))
        doc = ctx.index.documents[doc_id]
        return bm25_term_score(
            tf, df, doc.length, ctx.index.avg_doc_length, ctx.index.doc_count, ctx.k1, ctx.b
        )

    def __repr__(self):
        return f"Phrase({[t for _, t in self.offset_terms]!r})"


class ExpandingLeaf:
    """Shared base for wildcard/fuzzy leaves: they resolve to a set of real
    index terms, then behave like an OR of TermLeaf over those terms."""

    def expand(self, ctx):
        raise NotImplementedError

    def matched_docs(self, ctx):
        docs = set()
        for term in self.expand(ctx):
            docs |= set(ctx.index.postings.get(term, {}).keys())
        return docs

    def score_in_doc(self, ctx, doc_id):
        total = 0.0
        for term in self.expand(ctx):
            total += TermLeaf(term).score_in_doc(ctx, doc_id)
        return total


class WildcardLeaf(ExpandingLeaf):
    def __init__(self, prefix):
        self.prefix = prefix

    def expand(self, ctx):
        if ctx.trie is None:
            return []
        return ctx.trie.words_with_prefix(self.prefix)

    def __repr__(self):
        return f"Wildcard({self.prefix!r}*)"


class FuzzyLeaf(ExpandingLeaf):
    def __init__(self, word, max_dist):
        self.word = word
        self.max_dist = max_dist

    def expand(self, ctx):
        if ctx.bktree is None:
            return []
        return [w for w, _ in ctx.bktree.query(self.word, self.max_dist)]

    def __repr__(self):
        return f"Fuzzy({self.word!r}~{self.max_dist})"


class AndNode:
    def __init__(self, children):
        self.children = children

    def matched_docs(self, ctx):
        sets = [c.matched_docs(ctx) for c in self.children]
        result = sets[0]
        for s in sets[1:]:
            result = result & s
        return result


class OrNode:
    def __init__(self, children):
        self.children = children

    def matched_docs(self, ctx):
        result = set()
        for c in self.children:
            result |= c.matched_docs(ctx)
        return result


class NotNode:
    def __init__(self, child):
        self.child = child

    def matched_docs(self, ctx):
        return ctx.all_doc_ids() - self.child.matched_docs(ctx)


def collect_positive_leaves(node, negated=False):
    """Leaves that contribute positively to the final score: anything not
    under an odd number of NOT ancestors."""
    if isinstance(node, NotNode):
        return collect_positive_leaves(node.child, not negated)
    if isinstance(node, (AndNode, OrNode)):
        leaves = []
        for c in node.children:
            leaves.extend(collect_positive_leaves(c, negated))
        return leaves
    # leaf node
    return [] if negated else [node]


# --------------------------------------------------------------- tokenizer


def _tokenize(query_string):
    return _QUERY_TOKEN_RE.findall(query_string)


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def _is_keyword(self, tok, kw):
        return tok is not None and tok.lower() == kw

    def parse(self):
        if not self.tokens:
            raise QueryError("empty query")
        node = self.parse_or()
        if self.peek() is not None:
            raise QueryError(f"unexpected token {self.peek()!r}")
        return node

    def parse_or(self):
        nodes = [self.parse_and()]
        while self._is_keyword(self.peek(), "or"):
            self.advance()
            nodes.append(self.parse_and())
        return nodes[0] if len(nodes) == 1 else OrNode(nodes)

    def parse_and(self):
        nodes = [self.parse_not()]
        while True:
            tok = self.peek()
            if tok is None or tok == ")" or self._is_keyword(tok, "or"):
                break
            if self._is_keyword(tok, "and"):
                self.advance()
            nodes.append(self.parse_not())
        return nodes[0] if len(nodes) == 1 else AndNode(nodes)

    def parse_not(self):
        if self._is_keyword(self.peek(), "not"):
            self.advance()
            return NotNode(self.parse_not())
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok is None:
            raise QueryError("unexpected end of query")
        if tok == "(":
            self.advance()
            node = self.parse_or()
            if self.peek() != ")":
                raise QueryError("missing closing parenthesis")
            self.advance()
            return node
        if tok.startswith('"'):
            self.advance()
            return _build_phrase_leaf(tok[1:-1])
        self.advance()
        return _build_word_leaf(tok)


def _build_phrase_leaf(phrase_text):
    tokens = analyze(phrase_text)
    content = [(t.position, t.term) for t in tokens if t.term is not None]
    if not content:
        return PhraseLeaf([])
    base = content[0][0]
    offset_terms = [(pos - base, term) for pos, term in content]
    return PhraseLeaf(offset_terms)


def _build_word_leaf(tok):
    if tok.endswith("*") and len(tok) > 1:
        return WildcardLeaf(tok[:-1].lower())
    if "~" in tok:
        word, _, dist_str = tok.partition("~")
        max_dist = int(dist_str) if dist_str.strip().isdigit() else 2
        return FuzzyLeaf(analyze_query_term(word), max_dist)
    return TermLeaf(analyze_query_term(tok))


def parse_query(query_string):
    return _Parser(_tokenize(query_string)).parse()


def search(index, query_string, trie=None, bktree=None, k1=1.5, b=0.75):
    """Parse and evaluate a query string. Returns a list of
    (doc_id, score) sorted by score descending, doc_id ascending on ties."""
    ctx = QueryContext(index, trie=trie, bktree=bktree, k1=k1, b=b)
    root = parse_query(query_string)
    matched = root.matched_docs(ctx)
    positive_leaves = collect_positive_leaves(root)
    scored = []
    for doc_id in matched:
        score = sum(leaf.score_in_doc(ctx, doc_id) for leaf in positive_leaves)
        scored.append((doc_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored
