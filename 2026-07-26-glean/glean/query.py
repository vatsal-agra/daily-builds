"""Query parsing (boolean AND/OR/NOT + quoted phrases) and BM25 ranking.

Boolean semantics follow the classic Lucene BooleanQuery model:
  - MUST clauses (bare terms/phrases, or explicitly `AND`-joined) are
    intersected -- a doc must match every one.
  - MUST_NOT clauses (`NOT term`) are subtracted.
  - SHOULD clauses (`OR`-joined) are unioned; if there is at least one MUST
    clause, SHOULD clauses only add to the score rather than filter.
  - If there are no MUST clauses at all, the final result set is the union
    of SHOULD clauses (so a bare multi-word query like `raft consensus`
    behaves as "any of these, ranked by relevance").
A quoted "exact phrase" clause requires the analyzed phrase terms to occur
at consecutive positions in the document (accounting for stopwords removed
from both the query and the index consistently).
"""
import math
import re

from .analyzer import analyze
from .fuzzy import BKTree, levenshtein

K1 = 1.5
B = 0.75

_TOKEN_SPLIT_RE = re.compile(r'"[^"]*"|\S+')


class Clause:
    def __init__(self, kind, connector, negate, terms, raw):
        self.kind = kind  # "term" or "phrase"
        self.connector = connector  # "AND" or "OR"
        self.negate = negate
        self.terms = terms  # list of (stemmed_term, rel_pos)
        self.raw = raw


def parse_query(query_string):
    """Tokenize + analyze a query string into a list of Clause objects."""
    tokens = _TOKEN_SPLIT_RE.findall(query_string.strip())
    clauses = []
    pending_connector = None
    pending_negate = False

    for token in tokens:
        upper = token.upper()
        if upper == "AND":
            pending_connector = "AND"
            continue
        if upper == "OR":
            pending_connector = "OR"
            continue
        if upper == "NOT":
            pending_negate = True
            continue

        is_phrase = token.startswith('"') and token.endswith('"') and len(token) >= 2
        raw_text = token[1:-1] if is_phrase else token
        analyzed = analyze(raw_text)
        if not analyzed:
            pending_connector = None
            pending_negate = False
            continue

        connector = pending_connector or "OR"
        if is_phrase and len(analyzed) > 1:
            terms = [(t, p) for t, p, _raw in analyzed]
            clauses.append(Clause("phrase", connector, pending_negate, terms, raw_text))
        else:
            for t, _p, _raw in analyzed:
                clauses.append(Clause("term", connector, pending_negate, [(t, 0)], t))
                connector = "OR" if not is_phrase else connector

        pending_connector = None
        pending_negate = False

    return clauses


def _phrase_doc_positions(index, terms):
    """Return {doc_id: [phrase-start positions]} where all terms occur in order."""
    postings_by_term = [dict((d, p) for d, _tf, p in index.postings(t)) for t, _rel in terms]
    if not postings_by_term or any(not p for p in postings_by_term):
        return {}
    rel_positions = [rel for _t, rel in terms]
    base_rel = rel_positions[0]
    common_docs = set(postings_by_term[0])
    for p in postings_by_term[1:]:
        common_docs &= set(p)

    result = {}
    for doc_id in common_docs:
        candidate_starts = {pos - base_rel for pos in postings_by_term[0][doc_id]}
        for positions, rel in zip(postings_by_term[1:], rel_positions[1:]):
            offsets = {pos - rel for pos in positions[doc_id]}
            candidate_starts &= offsets
            if not candidate_starts:
                break
        if candidate_starts:
            result[doc_id] = sorted(candidate_starts)
    return result


def _idf(index, term):
    df = index.document_frequency(term)
    n = index.doc_count
    if df == 0 or n == 0:
        return 0.0
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def _bm25_term_score(index, term, doc_id, tf):
    doc = index.doc(doc_id)
    doc_len = doc["length"] if doc else 0
    avgdl = index.avg_doc_length or 1.0
    idf = _idf(index, term)
    denom = tf + K1 * (1 - B + B * (doc_len / avgdl))
    return idf * (tf * (K1 + 1)) / denom if denom else 0.0


def _clause_doc_scores(index, clause):
    """Return {doc_id: score} of docs matching this single clause."""
    if clause.kind == "term":
        term, _ = clause.terms[0]
        return {
            doc_id: _bm25_term_score(index, term, doc_id, tf)
            for doc_id, tf, _positions in index.postings(term)
        }
    # phrase
    starts = _phrase_doc_positions(index, clause.terms)
    scores = {}
    for doc_id in starts:
        total = 0.0
        for term, _rel in clause.terms:
            tf = next((tf for d, tf, _p in index.postings(term) if d == doc_id), 0)
            total += _bm25_term_score(index, term, doc_id, tf)
        scores[doc_id] = total
    return scores


def suggest_fuzzy(index, term, max_dist=2, limit=5):
    """BK-tree-based typo suggestions for a term with zero exact matches."""
    tree = BKTree(levenshtein)
    for vocab_term in index.vocabulary():
        tree.insert(vocab_term)
    matches = tree.search(term, max_dist)
    matches.sort(key=lambda m: (m[1], m[0]))
    return matches[:limit]


def search(index, query_string, limit=10, fuzzy=True):
    """Run a query against an index. Returns (results, suggestions, matched_terms).

    results: list of dicts {doc_id, path, title, score}
    suggestions: sorted list of fuzzy "did you mean" term strings, or []
    matched_terms: sorted list of stemmed terms used for scoring/highlighting
    """
    clauses = parse_query(query_string)
    suggestions = []
    if not clauses:
        return [], [], []

    if fuzzy:
        expanded = []
        for clause in clauses:
            new_terms = []
            for term, rel in clause.terms:
                if index.document_frequency(term) == 0:
                    hits = suggest_fuzzy(index, term, max_dist=2, limit=3)
                    if hits:
                        suggestions.extend(h[0] for h in hits)
                        best = hits[0][0]
                        new_terms.append((best, rel))
                        continue
                new_terms.append((term, rel))
            expanded.append(Clause(clause.kind, clause.connector, clause.negate, new_terms, clause.raw))
        clauses = expanded

    must, should, must_not = [], [], []
    for clause in clauses:
        if clause.negate:
            must_not.append(clause)
        elif clause.connector == "AND":
            must.append(clause)
        else:
            should.append(clause)

    must_scores = [_clause_doc_scores(index, c) for c in must]
    should_scores = [_clause_doc_scores(index, c) for c in should]
    must_not_docs = set()
    for c in must_not:
        must_not_docs |= set(_clause_doc_scores(index, c).keys())

    if must_scores:
        candidates = set(must_scores[0])
        for m in must_scores[1:]:
            candidates &= set(m)
    else:
        candidates = set()
        for s in should_scores:
            candidates |= set(s)

    candidates -= must_not_docs

    scored = []
    for doc_id in candidates:
        total = sum(m.get(doc_id, 0.0) for m in must_scores)
        total += sum(s.get(doc_id, 0.0) for s in should_scores)
        doc = index.doc(doc_id)
        if doc is None:
            continue
        scored.append((doc_id, total, doc))

    scored.sort(key=lambda r: (-r[1], r[2]["path"]))
    matched_terms = sorted({t for c in (must + should) for t, _ in c.terms})
    results = [
        {
            "doc_id": doc_id,
            "path": doc["path"],
            "title": doc["title"],
            "score": round(score, 4),
        }
        for doc_id, score, doc in scored[:limit]
    ]
    return results, sorted(set(suggestions)), matched_terms
