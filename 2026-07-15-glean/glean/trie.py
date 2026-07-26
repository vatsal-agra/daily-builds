"""A prefix trie over real (unstemmed) vocabulary words, for search-as-you-type
autocomplete ranked by how often each word occurs across the corpus."""

from collections import Counter

from . import tokenizer


class _TrieNode:
    __slots__ = ("children", "frequency")

    def __init__(self):
        self.children = {}
        self.frequency = 0  # >0 marks a complete word ending at this node


class Trie:
    def __init__(self):
        self.root = _TrieNode()

    def insert(self, word, count=1):
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, _TrieNode())
        node.frequency += count

    def contains(self, word):
        node = self._node_for_prefix(word)
        return node is not None and node.frequency > 0

    def _node_for_prefix(self, prefix):
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def complete(self, prefix, limit=10):
        """Return up to `limit` (word, frequency) completions of `prefix`,
        most frequent first, then alphabetically."""
        node = self._node_for_prefix(prefix)
        if node is None:
            return []
        results = []
        stack = [(node, prefix)]
        while stack:
            n, word = stack.pop()
            if n.frequency > 0:
                results.append((word, n.frequency))
            for ch, child in n.children.items():
                stack.append((child, word + ch))
        results.sort(key=lambda pair: (-pair[1], pair[0]))
        return results[:limit]


def raw_word_frequencies(index):
    """Count real (unstemmed) alphabetic words across every stored document."""
    freq = Counter()
    for doc in index.documents.values():
        for raw, _start, _end in tokenizer.tokenize(doc.text):
            if raw.isalpha():
                freq[raw] += 1
    return freq


def build_from_index(index, freq=None):
    """Build a Trie of real words (not stems) straight from each document's
    stored raw text, so autocomplete suggests whole dictionary words even
    though the search index itself only stores stems."""
    if freq is None:
        freq = raw_word_frequencies(index)
    trie = Trie()
    for word, count in freq.items():
        trie.insert(word, count)
    return trie
