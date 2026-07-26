"""Levenshtein edit distance + a BK-tree for typo-tolerant term lookup."""


def levenshtein(a, b):
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
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]


class BKTree:
    """Burkhard-Keller tree over a metric distance function (Levenshtein)."""

    def __init__(self, distance_fn=levenshtein):
        self.distance_fn = distance_fn
        self.root = None  # (word, {distance: child_node})

    def insert(self, word):
        if self.root is None:
            self.root = [word, {}]
            return
        node = self.root
        while True:
            d = self.distance_fn(word, node[0])
            if d == 0:
                return  # already present
            child = node[1].get(d)
            if child is None:
                node[1][d] = [word, {}]
                return
            node = child

    def search(self, word, max_dist):
        """Return [(match, distance), ...] within max_dist, sorted by distance."""
        if self.root is None:
            return []
        return sorted(self._search(self.root, word, max_dist, []), key=lambda r: r[1])

    def _search(self, node, word, max_dist, results):
        if node is None:
            return results
        d = self.distance_fn(word, node[0])
        if d <= max_dist:
            results.append((node[0], d))
        lo, hi = d - max_dist, d + max_dist
        for child_dist, child in node[1].items():
            if lo <= child_dist <= hi:
                self._search(child, word, max_dist, results)
        return results
