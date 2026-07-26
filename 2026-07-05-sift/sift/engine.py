"""Wires an InvertedIndex up with the auxiliary structures (trie, BK-tree)
needed for wildcard and fuzzy queries, and exposes a single search() entry
point that also builds snippets."""

from sift.trie import Trie
from sift.fuzzy import BKTree
from sift.query import search as _search
from sift.snippet import make_snippet


class Engine:
    def __init__(self, index):
        self.index = index
        vocab = index.vocabulary()

        self.trie = Trie()
        for term in vocab:
            self.trie.insert(term)

        self.bktree = None
        if vocab:
            self.bktree = BKTree(vocab[0])
            for term in vocab[1:]:
                self.bktree.insert(term)

    def search(self, query_string, k1=1.5, b=0.75, limit=10):
        results = _search(
            self.index, query_string, trie=self.trie, bktree=self.bktree, k1=k1, b=b
        )
        return results[:limit]

    def suggest(self, word, max_dist=2):
        """'Did you mean' suggestions for a single word: the closest
        vocabulary terms by edit distance."""
        if self.bktree is None:
            return []
        for radius in range(1, max_dist + 1):
            hits = self.bktree.query(word, radius)
            if hits:
                hits.sort(key=lambda pair: (pair[1], pair[0]))
                return hits
        return []

    def snippet_for(self, doc_id, query_string):
        doc = self.index.documents[doc_id]
        with open(doc.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        text = _strip_title_line(text, doc.title)
        from sift.query import parse_query, collect_positive_leaves, TermLeaf, PhraseLeaf

        try:
            root = parse_query(query_string)
        except Exception:
            return ""
        query_terms = set()
        for leaf in collect_positive_leaves(root):
            if isinstance(leaf, TermLeaf):
                query_terms.add(leaf.term)
            elif isinstance(leaf, PhraseLeaf):
                query_terms.update(term for _, term in leaf.offset_terms)
            else:
                query_terms.update(leaf.expand(_Ctx(self.index, self.trie, self.bktree)))
        return make_snippet(text, query_terms)


def _strip_title_line(text, title):
    """Drop the document's own title line before snippeting, so the search
    result card doesn't show the title twice (once as the card heading,
    once again inline at the top of the snippet)."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.lstrip("#").strip()
        if stripped:
            if stripped == title:
                return "".join(lines[i + 1 :])
            return text
    return text


class _Ctx:
    """Minimal stand-in for QueryContext, used only so ExpandingLeaf.expand()
    can be called from snippet_for() without re-parsing through search()."""

    def __init__(self, index, trie, bktree):
        self.index = index
        self.trie = trie
        self.bktree = bktree
