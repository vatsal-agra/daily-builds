"""Tokenization + stopword filtering + stemming pipeline."""

import re

from sift.stemmer import porter_stem

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

STOPWORDS = frozenset(
    """
    a an the and or but if while of at by for with about against between
    into through during before after above below to from up down in out
    on off over under again further then once here there when where why
    how all any both each few more most other some such no nor not only
    own same so than too very s t can will just don should now is are was
    were be been being have has had do does did this that these those it
    its i you he she we they them his her our your their as
    """.split()
)


class Token:
    __slots__ = ("raw", "start", "end", "position", "term")

    def __init__(self, raw, start, end, position, term):
        self.raw = raw
        self.start = start
        self.end = end
        self.position = position
        self.term = term

    def __repr__(self):
        return f"Token({self.raw!r}@{self.position})"


def tokenize_raw(text):
    """Split text into raw (surface-form) tokens with character offsets."""
    return [
        (m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)
    ]


def analyze(text, remove_stopwords=True, stem=True):
    """Full analysis pipeline: tokenize -> lowercase -> [stopword filter] ->
    [stem]. Returns a list of Token objects. `position` is the raw token's
    index in the document (stopwords still occupy a position slot even when
    filtered out, so positional/phrase queries remain correct across gaps).
    Tokens that are filtered (stopwords) have `term = None`.
    """
    tokens = []
    for position, (raw, start, end) in enumerate(tokenize_raw(text)):
        lowered = raw.lower()
        if remove_stopwords and lowered in STOPWORDS:
            tokens.append(Token(raw, start, end, position, None))
            continue
        term = porter_stem(lowered) if stem else lowered
        tokens.append(Token(raw, start, end, position, term))
    return tokens


def analyze_query_term(word, stem=True):
    """Normalize a single query word the same way indexed terms are
    normalized, so query terms and index terms live in the same space."""
    lowered = word.lower()
    return porter_stem(lowered) if stem else lowered
