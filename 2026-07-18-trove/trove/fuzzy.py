"""Levenshtein edit distance (from-scratch DP) and a BK-tree over the
index vocabulary, used to auto-correct query terms with no exact match."""


def levenshtein(a, b):
    """Classic O(len(a) * len(b)) edit-distance dynamic program."""
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
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]


class _BKNode:
    __slots__ = ("word", "children")

    def __init__(self, word):
        self.word = word
        self.children = {}  # distance -> _BKNode


class BKTree:
    """A Burkhard-Keller tree: indexes words by a metric distance function
    (Levenshtein here) so "find all words within distance k" runs in
    roughly O(log n) tree descents instead of scanning the full
    vocabulary for every query term."""

    def __init__(self, distance_fn=levenshtein):
        self.distance_fn = distance_fn
        self.root = None
        self.size = 0

    def add(self, word):
        self.size += 1
        if self.root is None:
            self.root = _BKNode(word)
            return
        node = self.root
        while True:
            d = self.distance_fn(word, node.word)
            if d == 0:
                return  # already present
            child = node.children.get(d)
            if child is None:
                node.children[d] = _BKNode(word)
                return
            node = child

    def build(self, words):
        for w in words:
            self.add(w)

    def query(self, word, max_distance):
        """Return [(match, distance), ...] for every indexed word within
        max_distance of `word`, sorted by (distance, alphabetically)."""
        if self.root is None:
            return []
        results = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            d = self.distance_fn(word, node.word)
            if d <= max_distance:
                results.append((node.word, d))
            # Triangle inequality: any match under a child edge-labelled
            # `dc` can only be within max_distance of `word` if
            # |d - dc| <= max_distance, so most children are pruned.
            for dc, child in node.children.items():
                if d - max_distance <= dc <= d + max_distance:
                    stack.append(child)
        results.sort(key=lambda item: (item[1], item[0]))
        return results


def build_bktree(index):
    """Build a BK-tree over an InvertedIndex's full vocabulary, used to
    fuzzy-correct query terms that don't appear in the index at all."""
    tree = BKTree()
    tree.build(index.vocabulary())
    return tree
