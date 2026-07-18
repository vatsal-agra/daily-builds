"""A small boolean/phrase/prefix query language, parsed by hand-written
recursive descent and evaluated over an InvertedIndex's postings lists.

Grammar (NOT binds tighter than AND, AND binds tighter than OR; AND is
also implicit between two adjacent terms with no operator, the way web
search engines treat a bare space):

    Expr    := AndExpr (OR AndExpr)*
    AndExpr := NotExpr (AND? NotExpr)*
    NotExpr := (NOT | '-')? Atom
    Atom    := '(' Expr ')' | PHRASE | PREFIX | WORD

Examples: `cdcl AND solver`, `cdcl solver` (implicit AND), `raft OR paxos`,
`"clause learning" -sudoku`, `comp* AND (bm25 OR tfidf)`.
"""

import re

from .tokenizer import normalize_term, STOPWORDS

_TOKEN_RE = re.compile(r'''
    (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<PHRASE>"[^"]*")
  | (?P<WORD>-?[A-Za-z0-9']+\*?)
  | (?P<JUNK>\S)
''', re.VERBOSE)

_KEYWORDS = {"AND", "OR", "NOT"}


class QuerySyntaxError(ValueError):
    pass


# ---- AST nodes ------------------------------------------------------
class And:
    def __init__(self, children):
        self.children = children


class Or:
    def __init__(self, children):
        self.children = children


class Not:
    def __init__(self, child):
        self.child = child


class Word:
    def __init__(self, raw):
        self.raw = raw


class Prefix:
    def __init__(self, raw):
        self.raw = raw


class Phrase:
    def __init__(self, words):
        self.words = words  # list of raw words, in order


# ---- lexer ------------------------------------------------------------
def _lex(text):
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        value = m.group()
        if kind == "JUNK":
            continue
        tokens.append((kind, value))
    return tokens


# ---- parser -----------------------------------------------------------
class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def advance(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def at_end(self):
        return self.pos >= len(self.tokens)

    def is_keyword(self, kw):
        kind, value = self.peek()
        return kind == "WORD" and value.upper() == kw and value.upper() in _KEYWORDS

    def parse(self):
        if self.at_end():
            return None
        node = self.parse_or()
        if not self.at_end():
            kind, value = self.peek()
            raise QuerySyntaxError(f"unexpected token {value!r}")
        return node

    def parse_or(self):
        children = [self.parse_and()]
        while self.is_keyword("OR"):
            self.advance()
            children.append(self.parse_and())
        return children[0] if len(children) == 1 else Or(children)

    def parse_and(self):
        children = [self.parse_not()]
        while True:
            if self.is_keyword("OR") or self.at_end():
                break
            kind, value = self.peek()
            if kind == "RPAREN":
                break
            if self.is_keyword("AND"):
                self.advance()
            children.append(self.parse_not())
        return children[0] if len(children) == 1 else And(children)

    def parse_not(self):
        if self.is_keyword("NOT"):
            self.advance()
            return Not(self.parse_not())
        kind, value = self.peek()
        if kind == "WORD" and value.startswith("-") and len(value) > 1:
            self.advance()
            return Not(self._word_or_prefix(value[1:]))
        return self.parse_atom()

    def parse_atom(self):
        kind, value = self.peek()
        if kind is None:
            raise QuerySyntaxError("unexpected end of query")
        if kind == "LPAREN":
            self.advance()
            node = self.parse_or()
            kind2, value2 = self.peek()
            if kind2 != "RPAREN":
                raise QuerySyntaxError("missing closing ')'")
            self.advance()
            return node
        if kind == "RPAREN":
            raise QuerySyntaxError("unexpected ')'")
        if kind == "PHRASE":
            self.advance()
            inner = value[1:-1]
            words = [w for w in re.findall(r"[A-Za-z0-9']+", inner)]
            return Phrase(words)
        if kind == "WORD":
            if value.upper() in _KEYWORDS:
                raise QuerySyntaxError(f"unexpected keyword {value!r}")
            self.advance()
            return self._word_or_prefix(value)
        raise QuerySyntaxError(f"unexpected token {value!r}")

    @staticmethod
    def _word_or_prefix(value):
        if value.endswith("*") and len(value) > 1:
            return Prefix(value[:-1])
        return Word(value)


def parse_query(text):
    tokens = _lex(text)
    return _Parser(tokens).parse()


# ---- evaluation ---------------------------------------------------------
class QueryResult:
    def __init__(self, doc_ids, terms, corrections):
        self.doc_ids = doc_ids
        self.terms = terms                # positive terms, for ranking
        self.corrections = corrections    # [(typed, corrected)]


class _Empty:
    doc_ids = frozenset()
    terms = frozenset()


def _resolve_term(index, raw_word, corrections, fuzzy_corrector, fuzzy_max_distance):
    term = normalize_term(raw_word)
    if not term:
        return None
    if index.doc_freq(term) > 0:
        return term
    if fuzzy_corrector is None:
        return None
    matches = fuzzy_corrector.query(term, fuzzy_max_distance)
    if not matches:
        return None
    best_term, _dist = matches[0]
    display = index.term_surface.get(best_term, best_term)
    corrections.append((raw_word.lower(), display))
    return best_term


def _eval(node, index, corrections, fuzzy_corrector, fuzzy_max_distance):
    if isinstance(node, And):
        results = [_eval(c, index, corrections, fuzzy_corrector, fuzzy_max_distance) for c in node.children]
        doc_ids = results[0].doc_ids
        for r in results[1:]:
            doc_ids = doc_ids & r.doc_ids
        terms = set()
        for r in results:
            terms |= r.terms
        return QueryResult(doc_ids, terms, [])

    if isinstance(node, Or):
        results = [_eval(c, index, corrections, fuzzy_corrector, fuzzy_max_distance) for c in node.children]
        doc_ids = set()
        terms = set()
        for r in results:
            doc_ids |= r.doc_ids
            terms |= r.terms
        return QueryResult(doc_ids, terms, [])

    if isinstance(node, Not):
        inner = _eval(node.child, index, corrections, fuzzy_corrector, fuzzy_max_distance)
        doc_ids = index.all_doc_ids() - inner.doc_ids
        return QueryResult(doc_ids, set(), [])

    if isinstance(node, Word):
        term = _resolve_term(index, node.raw, corrections, fuzzy_corrector, fuzzy_max_distance)
        if term is None:
            return QueryResult(set(), set(), [])
        return QueryResult(set(index.postings_for(term).keys()), {term}, [])

    if isinstance(node, Prefix):
        prefix = node.raw.lower()
        if not prefix:
            return QueryResult(set(), set(), [])
        matches = [t for t in index.vocabulary() if t.startswith(prefix)]
        doc_ids = set()
        for t in matches:
            doc_ids |= set(index.postings_for(t).keys())
        return QueryResult(doc_ids, set(matches), [])

    if isinstance(node, Phrase):
        return _eval_phrase(node, index, corrections, fuzzy_corrector, fuzzy_max_distance)

    raise TypeError(f"unknown AST node: {node!r}")


def _eval_phrase(node, index, corrections, fuzzy_corrector, fuzzy_max_distance):
    terms = []
    for w in node.words:
        if w.lower() in STOPWORDS:
            continue
        term = _resolve_term(index, w, corrections, fuzzy_corrector, fuzzy_max_distance)
        if term is None:
            return QueryResult(set(), set(), [])
        terms.append(term)

    if not terms:
        return QueryResult(set(), set(), [])
    if len(terms) == 1:
        t = terms[0]
        return QueryResult(set(index.postings_for(t).keys()), {t}, [])

    candidate_docs = set(index.postings_for(terms[0]).keys())
    for t in terms[1:]:
        candidate_docs &= set(index.postings_for(t).keys())

    matching_docs = set()
    for doc_id in candidate_docs:
        first_positions = set(index.postings_for(terms[0])[doc_id])
        starts = first_positions
        for offset, t in enumerate(terms[1:], start=1):
            t_positions = set(index.postings_for(t)[doc_id])
            starts = {s for s in starts if (s + offset) in t_positions}
            if not starts:
                break
        if starts:
            matching_docs.add(doc_id)

    return QueryResult(matching_docs, set(terms), [])


def evaluate(index, query_text, fuzzy_corrector=None, fuzzy_max_distance=2):
    """Parse and evaluate `query_text` against `index`. Returns a
    QueryResult with the matching doc_ids, the positive terms to rank by,
    and any (typed, corrected) fuzzy substitutions that were made."""
    ast = parse_query(query_text)
    if ast is None:
        return QueryResult(set(), set(), [])
    corrections = []
    result = _eval(ast, index, corrections, fuzzy_corrector, fuzzy_max_distance)
    return QueryResult(result.doc_ids, result.terms, corrections)
