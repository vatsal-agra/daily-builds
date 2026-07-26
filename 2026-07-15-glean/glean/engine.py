"""Search() ties the index, query parser and ranker together into the
single call most callers actually want."""

from dataclasses import dataclass

from . import query as query_mod
from . import rank
from . import trie as trie_mod
from .fuzzy import FuzzyIndex
from .index import InvertedIndex
from .tokenizer import porter_stem


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
        self._fuzzy = None
        self._trie = None
        self._stem_display = None

    def add_document(self, title, text, path=None):
        doc_id = self.index.add_document(title, text, path=path)
        self._fuzzy = None  # vocabulary changed; rebuild lazily on next use
        self._trie = None
        self._stem_display = None
        return doc_id

    @property
    def fuzzy_index(self):
        if self._fuzzy is None:
            self._fuzzy = FuzzyIndex(self.index)
        return self._fuzzy

    @property
    def autocomplete_trie(self):
        if self._trie is None:
            self._trie = trie_mod.build_from_index(self.index)
        return self._trie

    def _stem_to_display_word(self, stem):
        """Best human-readable raw word for a stem: the most frequent raw
        word across the corpus that stems to it, falling back to the stem
        itself if nothing does."""
        if self._stem_display is None:
            freq = trie_mod.raw_word_frequencies(self.index)
            best = {}
            for word, count in freq.items():
                key = porter_stem(word)
                current = best.get(key)
                if current is None or count > current[1] or (count == current[1] and word < current[0]):
                    best[key] = (word, count)
            self._stem_display = {k: v[0] for k, v in best.items()}
        return self._stem_display.get(stem, stem)

    def autocomplete(self, prefix, limit=10):
        """Search-as-you-type suggestions: real dictionary words from the
        corpus, ranked by frequency, that start with `prefix`."""
        prefix = prefix.lower().strip()
        if not prefix:
            return []
        return [word for word, _freq in self.autocomplete_trie.complete(prefix, limit=limit)]

    def did_you_mean(self, query_string, max_distance=2):
        """For each bare term in `query_string` with zero postings, look up
        the closest edit-distance vocabulary terms via the BK-tree, mapped
        back to a real, human-readable word for display. Returns a dict of
        {missing_term: [(display_word, distance), ...]}; empty if every term
        already matches something (or the query has no terms)."""
        try:
            ast = query_mod.parse(query_string)
        except query_mod.QuerySyntaxError:
            return {}
        suggestions = {}
        for term in set(query_mod.positive_terms(ast)):
            if not term or term in self.index.postings:
                continue
            candidates = self.fuzzy_index.suggest(term, max_distance=max_distance)
            if candidates:
                suggestions[term] = [
                    (self._stem_to_display_word(stem), distance) for stem, distance in candidates
                ]
        return suggestions

    def search(self, query_string, top_k=10):
        """Parse `query_string`, execute it, rank candidates with BM25, and
        return SearchResult objects with highlighted snippets."""
        top_k = max(0, top_k)
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
