"""Typo-tolerant term matching: a from-scratch Levenshtein edit-distance DP
and a BK-tree index over the vocabulary for fast bounded-distance lookup."""


def levenshtein(a, b):
    """Minimum single-character insert/delete/substitute edits to turn a into b."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


class _BKNode:
    __slots__ = ("word", "children")

    def __init__(self, word):
        self.word = word
        self.children = {}  # distance -> _BKNode


class BKTree:
    """A Burkhard-Keller tree: an index over a metric space (here, edit
    distance) that lets a bounded-distance search prune whole subtrees via
    the triangle inequality instead of comparing against every entry."""

    def __init__(self, distance_fn=levenshtein):
        self.distance_fn = distance_fn
        self.root = None
        self._size = 0

    def __len__(self):
        return self._size

    def add(self, word):
        if self.root is None:
            self.root = _BKNode(word)
            self._size += 1
            return
        node = self.root
        while True:
            d = self.distance_fn(word, node.word)
            if d == 0:
                return  # already present
            child = node.children.get(d)
            if child is None:
                node.children[d] = _BKNode(word)
                self._size += 1
                return
            node = child

    def search(self, word, max_distance):
        """Return [(match, distance), ...] for every indexed word within
        `max_distance` edits of `word`, closest first."""
        if self.root is None:
            return []
        results = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            d = self.distance_fn(word, node.word)
            if d <= max_distance:
                results.append((node.word, d))
            lo, hi = d - max_distance, d + max_distance
            for dist, child in node.children.items():
                if lo <= dist <= hi:
                    stack.append(child)
        results.sort(key=lambda pair: (pair[1], pair[0]))
        return results


class FuzzyIndex:
    """A BK-tree over an InvertedIndex's stemmed vocabulary, for typo-tolerant
    matching and "did you mean" suggestions."""

    def __init__(self, index):
        self.tree = BKTree()
        for term in index.postings:
            self.tree.add(term)

    def suggest(self, term, max_distance=2, limit=5):
        return self.tree.search(term, max_distance)[:limit]
