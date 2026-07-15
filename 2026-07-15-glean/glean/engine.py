"""Search() ties the index, query parser and ranker together into the
single call most callers actually want."""

from dataclasses import dataclass

from . import query as query_mod
from . import rank
from .index import InvertedIndex


@dataclass
class SearchResult:
    doc_id: int
    title: str
    path: str
    score: float
    snippet_pieces: list


class SearchEngine:
    def __init__(self, index=None):
        self.index = index or InvertedIndex()
        self.scorer = rank.BM25(self.index)

    def add_document(self, title, text, path=None):
        return self.index.add_document(title, text, path=path)

    def search(self, query_string, top_k=10):
        """Parse `query_string`, execute it, rank candidates with BM25, and
        return SearchResult objects with highlighted snippets."""
        ast = query_mod.parse(query_string)
        candidates = ast.match(self.index)
        terms = [t for t in query_mod.positive_terms(ast) if t]
        if not terms:
            ranked = [(doc_id, 0.0) for doc_id in sorted(candidates)][:top_k]
        else:
            ranked = self.scorer.rank(candidates, terms, top_k=top_k)
        results = []
        for doc_id, score in ranked:
            doc = self.index.documents[doc_id]
            pieces = rank.build_snippet(doc, set(terms))
            results.append(SearchResult(doc_id, doc.title, doc.path, score, pieces))
        return results

    def stats(self):
        return {
            "documents": self.index.doc_count,
            "vocabulary": len(self.index.postings),
            "avg_doc_length": round(self.index.avg_doc_length, 2),
        }

    def save(self, path):
        self.index.save(path)

    @classmethod
    def load(cls, path):
        return cls(InvertedIndex.load(path))
