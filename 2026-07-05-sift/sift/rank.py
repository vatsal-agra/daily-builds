"""Okapi BM25 ranking, plus an independent brute-force oracle for testing."""

import math

K1_DEFAULT = 1.5
B_DEFAULT = 0.75


def idf(doc_count, doc_freq):
    """Lucene/BM25+-style non-negative IDF: log(1 + (N - df + 0.5)/(df + 0.5))."""
    return math.log(1.0 + (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))


def bm25_term_score(tf, df, doc_len, avg_doc_len, doc_count, k1=K1_DEFAULT, b=B_DEFAULT):
    if tf == 0:
        return 0.0
    idf_val = idf(doc_count, df)
    denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len if avg_doc_len else 1.0))
    return idf_val * (tf * (k1 + 1)) / denom


def score_document(index, doc_id, term_list, k1=K1_DEFAULT, b=B_DEFAULT):
    """Sum BM25 term scores for a document over a list of (term, tf, df)
    triples already resolved from the index or a phrase match."""
    doc = index.documents[doc_id]
    total = 0.0
    for term, tf, df in term_list:
        total += bm25_term_score(
            tf, df, doc.length, index.avg_doc_length, index.doc_count, k1, b
        )
    return total


def bruteforce_bm25(corpus_texts, query_terms, target_doc_id, k1=K1_DEFAULT, b=B_DEFAULT):
    """Independent re-implementation used only to verify the indexed path:
    re-tokenizes every document from raw text (not via InvertedIndex) and
    recomputes tf/df/N/avgdl/BM25 from first principles.

    `corpus_texts` is a list of raw document strings; `query_terms` are
    already-stemmed query terms.
    """
    from sift.analyzer import analyze

    doc_count = len(corpus_texts)
    per_doc_terms = []
    lengths = []
    for text in corpus_texts:
        terms = [t.term for t in analyze(text) if t.term is not None]
        per_doc_terms.append(terms)
        lengths.append(len(terms))
    avg_len = sum(lengths) / doc_count if doc_count else 0.0

    total = 0.0
    target_terms = per_doc_terms[target_doc_id]
    target_len = lengths[target_doc_id]
    for term in query_terms:
        tf = target_terms.count(term)
        if tf == 0:
            continue
        df = sum(1 for terms in per_doc_terms if term in terms)
        total += bm25_term_score(tf, df, target_len, avg_len, doc_count, k1, b)
    return total
