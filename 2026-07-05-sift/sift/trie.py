"""A prefix trie over the index vocabulary, for wildcard/prefix queries."""


class TrieNode:
    __slots__ = ("children", "is_end")

    def __init__(self):
        self.children = {}
        self.is_end = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, TrieNode())
        node.is_end = True

    def _collect(self, node, prefix, out):
        if node.is_end:
            out.append(prefix)
        for ch, child in node.children.items():
            self._collect(child, prefix + ch, out)

    def words_with_prefix(self, prefix):
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return []
        out = []
        self._collect(node, prefix, out)
        return sorted(out)
