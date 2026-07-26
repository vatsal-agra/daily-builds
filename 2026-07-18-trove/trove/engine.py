"""High-level facade tying index + query + ranking + fuzzy correction
together into a single `search()` call, shared by the CLI and the server
so there is exactly one implementation of "what does a search do"."""

import time

from . import query as query_mod
from . import ranking
from .fuzzy import build_bktree
from .index import InvertedIndex
from .snippet import make_snippet
from .suggest import build_trie

# Ample for any real query (the longest phrase/boolean query in this
# project's own test suite is well under 100 chars); bounds worst-case
# parenthesis-nesting depth the recursive-descent parser can be handed,
# so pathological input can't drive it into RecursionError.
MAX_QUERY_LENGTH = 300


class SearchResult:
    def __init__(self, doc_id, title, path, score, snippet=""):
        self.doc_id = doc_id
        self.title = title
        self.path = path
        self.score = score
        self.snippet = snippet

    def to_dict(self):
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "path": self.path,
            "score": round(self.score, 4),
            "snippet": self.snippet,
        }


class Engine:
    def __init__(self, index):
        self.index = index
        self.bktree = build_bktree(index) if index.N else None
        self.trie = build_trie(index) if index.N else None

    @classmethod
    def load(cls, path):
        return cls(InvertedIndex.load(path))

    def search(self, query_text, top=10, k1=1.5, b=0.75, fuzzy_max_distance="auto"):
        start = time.perf_counter()
        query_text = (query_text or "").strip()[:MAX_QUERY_LENGTH]
        top = max(0, top)
        if not query_text:
            return {
                "query": query_text,
                "results": [],
                "corrections": [],
                "total_matches": 0,
                "took_ms": 0.0,
                "error": None,
            }
        try:
            result = query_mod.evaluate(
                self.index, query_text,
                fuzzy_corrector=self.bktree,
                fuzzy_max_distance=fuzzy_max_distance,
                trie=self.trie,
            )
        except (query_mod.QuerySyntaxError, RecursionError) as e:
            message = str(e) if isinstance(e, query_mod.QuerySyntaxError) else "query too deeply nested"
            return {
                "query": query_text,
                "results": [],
                "corrections": [],
                "total_matches": 0,
                "took_ms": round((time.perf_counter() - start) * 1000, 3),
                "error": message,
            }

        if not result.terms:
            # A pure NOT / prefix-miss query has a doc set but nothing to
            # rank by; fall back to stable doc_id order.
            ranked = [(doc_id, 0.0) for doc_id in sorted(result.doc_ids)][:top]
        else:
            ranked = ranking.rank(self.index, result.terms, result.doc_ids, top=top, k1=k1, b=b)

        results = []
        for doc_id, score in ranked:
            meta = self.index.doc_meta[doc_id]
            snippet = make_snippet(meta["text"], result.terms)
            results.append(SearchResult(doc_id, meta["title"], meta["path"], score, snippet))

        took_ms = round((time.perf_counter() - start) * 1000, 3)
        return {
            "query": query_text,
            "results": results,
            "corrections": result.corrections,
            "total_matches": len(result.doc_ids),
            "took_ms": took_ms,
            "error": None,
        }

    def suggest(self, prefix, limit=8):
        prefix = (prefix or "").strip()[:MAX_QUERY_LENGTH]
        if not prefix or self.trie is None:
            return []
        matches = self.trie.suggest(prefix, limit=limit)
        return [self.index.term_surface.get(term, term) for term, _freq in matches]
