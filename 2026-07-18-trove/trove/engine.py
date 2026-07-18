"""High-level facade tying index + query + ranking + fuzzy correction
together into a single `search()` call, shared by the CLI and the server
so there is exactly one implementation of "what does a search do"."""

import time

from . import query as query_mod
from . import ranking
from .fuzzy import build_bktree
from .index import InvertedIndex


class SearchResult:
    def __init__(self, doc_id, title, path, score):
        self.doc_id = doc_id
        self.title = title
        self.path = path
        self.score = score

    def to_dict(self):
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "path": self.path,
            "score": round(self.score, 4),
        }


class Engine:
    def __init__(self, index):
        self.index = index
        self.bktree = build_bktree(index) if index.N else None

    @classmethod
    def load(cls, path):
        return cls(InvertedIndex.load(path))

    def search(self, query_text, top=10, k1=1.5, b=0.75, fuzzy_max_distance=2):
        start = time.perf_counter()
        query_text = (query_text or "").strip()
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
            )
        except query_mod.QuerySyntaxError as e:
            return {
                "query": query_text,
                "results": [],
                "corrections": [],
                "total_matches": 0,
                "took_ms": round((time.perf_counter() - start) * 1000, 3),
                "error": str(e),
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
            results.append(SearchResult(doc_id, meta["title"], meta["path"], score))

        took_ms = round((time.perf_counter() - start) * 1000, 3)
        return {
            "query": query_text,
            "results": results,
            "corrections": result.corrections,
            "total_matches": len(result.doc_ids),
            "took_ms": took_ms,
            "error": None,
        }
