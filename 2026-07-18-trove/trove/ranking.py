"""Okapi BM25 ranking over an InvertedIndex."""

import math
from collections import defaultdict


def idf(index, term):
    """Lucene-style BM25 IDF: always non-negative (unlike the classic
    Robertson-Sparck Jones form, which goes negative for terms in more
    than half the corpus)."""
    df = index.doc_freq(term)
    n = index.N
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def bm25_term_score(index, term, doc_id, k1=1.5, b=0.75):
    postings = index.postings_for(term)
    positions = postings.get(doc_id)
    if not positions:
        return 0.0
    tf = len(positions)
    dl = index.doc_lengths[doc_id]
    avgdl = index.avg_doc_length or 1.0
    denom = tf + k1 * (1 - b + b * (dl / avgdl))
    return idf(index, term) * (tf * (k1 + 1)) / denom


def bm25_scores(index, terms, candidate_doc_ids, k1=1.5, b=0.75):
    """Score every doc in `candidate_doc_ids` against the (stemmed) query
    `terms`, summing per-term BM25 contributions. Returns a dict
    doc_id -> score, omitting docs with zero total score."""
    scores = defaultdict(float)
    for term in terms:
        postings = index.postings_for(term)
        if not postings:
            continue
        for doc_id in candidate_doc_ids:
            if doc_id in postings:
                scores[doc_id] += bm25_term_score(index, term, doc_id, k1, b)
    return dict(scores)


def rank(index, terms, candidate_doc_ids, top=10, k1=1.5, b=0.75):
    scores = bm25_scores(index, terms, candidate_doc_ids, k1, b)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:top]
