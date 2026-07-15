"""Relevance ranking: Okapi BM25 (primary) and TF-IDF cosine (comparison),
plus highlighted snippet extraction."""

import math
from collections import Counter


class BM25:
    def __init__(self, index, k1=1.5, b=0.75):
        self.index = index
        self.k1 = k1
        self.b = b

    def idf(self, term):
        n_t = len(self.index.postings.get(term, {}))
        N = self.index.doc_count
        if n_t == 0 or N == 0:
            return 0.0
        return math.log((N - n_t + 0.5) / (n_t + 0.5) + 1)

    def score(self, doc_id, query_terms):
        doc = self.index.documents.get(doc_id)
        if doc is None:
            return 0.0
        avgdl = self.index.avg_doc_length or 1.0
        term_counts = Counter(query_terms)
        total = 0.0
        for term, qtf in term_counts.items():
            postings = self.index.postings.get(term)
            if not postings or doc_id not in postings:
                continue
            f = len(postings[doc_id])
            idf = self.idf(term)
            denom = f + self.k1 * (1 - self.b + self.b * (doc.length / avgdl))
            if denom == 0:
                continue
            total += qtf * idf * (f * (self.k1 + 1)) / denom
        return total

    def rank(self, candidate_doc_ids, query_terms, top_k=10):
        scored = [(doc_id, self.score(doc_id, query_terms)) for doc_id in candidate_doc_ids]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_k]


class TfIdfCosine:
    """Cosine similarity over TF-IDF vectors, provided as a comparison scorer."""

    def __init__(self, index):
        self.index = index

    def idf(self, term):
        n_t = len(self.index.postings.get(term, {}))
        N = self.index.doc_count
        if n_t == 0 or N == 0:
            return 0.0
        return math.log(N / n_t)

    def _doc_vector(self, doc_id, terms):
        doc = self.index.documents[doc_id]
        vec = {}
        for term in terms:
            postings = self.index.postings.get(term, {})
            tf = len(postings.get(doc_id, []))
            if tf == 0:
                continue
            vec[term] = (tf / doc.length if doc.length else 0.0) * self.idf(term)
        return vec

    def score(self, doc_id, query_terms):
        query_counts = Counter(query_terms)
        query_vec = {t: c * self.idf(t) for t, c in query_counts.items()}
        doc_vec = self._doc_vector(doc_id, query_counts.keys())
        dot = sum(query_vec.get(t, 0.0) * doc_vec.get(t, 0.0) for t in query_counts)
        qnorm = math.sqrt(sum(v * v for v in query_vec.values()))
        dnorm = math.sqrt(sum(v * v for v in doc_vec.values()))
        if qnorm == 0 or dnorm == 0:
            return 0.0
        return dot / (qnorm * dnorm)

    def rank(self, candidate_doc_ids, query_terms, top_k=10):
        scored = [(doc_id, self.score(doc_id, query_terms)) for doc_id in candidate_doc_ids]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_k]


def build_snippet(doc, match_terms, radius=8):
    """Return a list of (text_chunk, is_match) pieces centered on the densest
    cluster of matched terms, suitable for either plain-text or HTML rendering."""
    match_terms = set(match_terms)
    if not doc.tokens:
        return [(doc.text[:200], False)]

    idxs = [i for i, t in enumerate(doc.tokens) if t in match_terms]
    center = idxs[len(idxs) // 2] if idxs else 0
    start_idx = max(0, center - radius)
    end_idx = min(len(doc.tokens), center + radius + 1)

    text_start = doc.spans[start_idx][0]
    cursor = text_start
    pieces = []
    for i in range(start_idx, end_idx):
        s, e = doc.spans[i]
        if s > cursor:
            pieces.append((doc.text[cursor:s], False))
        pieces.append((doc.text[s:e], doc.tokens[i] in match_terms))
        cursor = e

    if start_idx > 0:
        pieces.insert(0, ("…", False))
    if end_idx < len(doc.tokens):
        pieces.append(("…", False))
    return pieces


def snippet_to_text(pieces, mark_start="**", mark_end="**"):
    out = []
    for chunk, is_match in pieces:
        out.append(f"{mark_start}{chunk}{mark_end}" if is_match else chunk)
    return "".join(out)


def snippet_to_html(pieces):
    import html as _html
    out = []
    for chunk, is_match in pieces:
        escaped = _html.escape(chunk)
        out.append(f"<mark>{escaped}</mark>" if is_match else escaped)
    return "".join(out)
