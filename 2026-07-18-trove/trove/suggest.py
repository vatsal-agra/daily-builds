"""A from-scratch trie over the index vocabulary for search-as-you-type
autocomplete, ranked by corpus frequency (documents containing the term)
so common terms surface before rare ones."""


class _TrieNode:
    __slots__ = ("children", "is_word", "freq")

    def __init__(self):
        self.children = {}
        self.is_word = False
        self.freq = 0


class Trie:
    def __init__(self):
        self.root = _TrieNode()

    def insert(self, word, freq=1):
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, _TrieNode())
        node.is_word = True
        node.freq = max(node.freq, freq)

    def _node_at(self, prefix):
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def _collect(self, node, prefix, out):
        if node.is_word:
            out.append((prefix, node.freq))
        for ch, child in node.children.items():
            self._collect(child, prefix + ch, out)

    def suggest(self, prefix, limit=10):
        """All indexed words starting with `prefix`, most-frequent first
        (alphabetical tiebreak), capped at `limit`."""
        prefix = prefix.lower()
        if not prefix:
            return []
        start = self._node_at(prefix)
        if start is None:
            return []
        results = []
        self._collect(start, prefix, results)
        results.sort(key=lambda item: (-item[1], item[0]))
        return results[:limit]

    def prefix_matches(self, prefix):
        """All indexed words starting with `prefix` (unranked, unlimited)
        — used to accelerate boolean `term*` prefix queries instead of a
        linear vocabulary scan."""
        prefix = prefix.lower()
        if not prefix:
            return []
        start = self._node_at(prefix)
        if start is None:
            return []
        results = []
        self._collect(start, prefix, results)
        return [w for w, _freq in results]


def build_trie(index):
    """Build a Trie over an InvertedIndex's vocabulary, weighted by
    document frequency (how many documents contain the term)."""
    trie = Trie()
    for term in index.vocabulary():
        trie.insert(term, freq=index.doc_freq(term))
    return trie
