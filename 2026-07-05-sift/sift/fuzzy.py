"""Levenshtein edit distance + a BK-tree for fast fuzzy vocabulary lookup."""


def levenshtein(a, b):
    """Classic O(n*m) dynamic-programming edit distance (insert/delete/substitute,
    unit cost). Used both as the BK-tree's metric and as an independent
    brute-force oracle to verify BK-tree query results against."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[m]


class BKTree:
    """Burkhard-Keller tree over a metric distance function (Levenshtein).
    Supports insert() and a range query() that prunes subtrees using the
    triangle inequality: |d(query,node) - d(query,child)| edges are bucketed
    by exact distance, so any candidate whose bucket distance d differs from
    the query-to-node distance by more than the search radius can't possibly
    be within radius and its whole subtree is skipped.
    """

    __slots__ = ("word", "children", "distance_fn")

    def __init__(self, word, distance_fn=levenshtein):
        self.word = word
        self.children = {}  # distance -> BKTree
        self.distance_fn = distance_fn

    def insert(self, word):
        d = self.distance_fn(self.word, word)
        if d == 0:
            return  # duplicate, already present
        child = self.children.get(d)
        if child is None:
            self.children[d] = BKTree(word, self.distance_fn)
        else:
            child.insert(word)

    def query(self, word, max_dist):
        """Return [(candidate, distance), ...] for every indexed word within
        max_dist of `word`."""
        results = []
        d = self.distance_fn(self.word, word)
        if d <= max_dist:
            results.append((self.word, d))
        lo, hi = d - max_dist, d + max_dist
        for child_dist, child in self.children.items():
            if lo <= child_dist <= hi:
                results.extend(child.query(word, max_dist))
        return results


def naive_fuzzy_search(vocabulary, word, max_dist):
    """Brute-force oracle: Levenshtein against every vocabulary word."""
    return [(w, levenshtein(w, word)) for w in vocabulary if levenshtein(w, word) <= max_dist]
