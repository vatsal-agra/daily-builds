"""Text -> filtered, stemmed token stream, plus raw token offsets for
snippet generation. Pure stdlib, built on the from-scratch Porter stemmer."""

import re

from .stemmer import stem

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")

# A standard English stopword list (function words that carry no topical
# signal and would otherwise dominate every posting list).
STOPWORDS = frozenset("""
a about above after again against all am an and any are aren't as at be
because been before being below between both but by can't cannot could
couldn't did didn't do does doesn't doing don't down during each few for
from further had hadn't has hasn't have haven't having he he'd he'll he's
her here here's hers herself him himself his how how's i i'd i'll i'm i've
if in into is isn't it it's its itself let's me more most mustn't my myself
no nor not of off on once only or other ought our ours ourselves out over
own same shan't she she'd she'll she's should shouldn't so some such than
that that's the their theirs them themselves then there there's these they
they'd they'll they're they've this those through to too under until up
very was wasn't we we'd we'll we're we've were weren't what what's when
when's where where's which while who who's whom why why's with won't would
wouldn't you you'd you'll you're you've your yours yourself yourselves
""".split())


class Token:
    __slots__ = ("term", "raw", "start", "end")

    def __init__(self, term, raw, start, end):
        self.term = term      # stemmed, lowercase
        self.raw = raw        # original surface form
        self.start = start    # char offset into source text
        self.end = end

    def __repr__(self):
        return f"Token({self.term!r}, raw={self.raw!r}, {self.start}:{self.end})"


def raw_tokens(text):
    """All word-like tokens in original order with char offsets, no
    filtering — used by the snippet extractor, which needs every word
    (including stopwords) to reconstruct readable context."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def tokenize(text, remove_stopwords=True):
    """Return the filtered, stemmed Token stream used for indexing and
    querying. Position in this list (post stopword-removal) is what
    phrase-query positional matching operates over."""
    tokens = []
    for word, start, end in raw_tokens(text):
        lower = word.lower()
        if remove_stopwords and lower in STOPWORDS:
            continue
        term = stem(lower)
        if not term:
            continue
        tokens.append(Token(term, word, start, end))
    return tokens


def normalize_term(word):
    """Stem a single free-standing query word the same way indexed terms
    were stemmed, so lookups compare like with like."""
    return stem(word.lower())
