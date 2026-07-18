import os
import random
import string
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.fuzzy import levenshtein, BKTree


class TestLevenshtein(unittest.TestCase):
    def test_known_distances(self):
        cases = [
            ("", "", 0),
            ("", "abc", 3),
            ("abc", "", 3),
            ("kitten", "sitting", 3),
            ("flaw", "lawn", 2),
            ("intention", "execution", 5),
            ("same", "same", 0),
            ("a", "b", 1),
            ("spreadsheet", "spreadhseet", 2),  # transposition = 2 edits
        ]
        for a, b, expected in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(levenshtein(a, b), expected)

    def test_symmetric(self):
        pairs = [("kitten", "sitting"), ("saturday", "sunday"), ("", "x"), ("abc", "abcabc")]
        for a, b in pairs:
            self.assertEqual(levenshtein(a, b), levenshtein(b, a))

    def test_triangle_inequality_random(self):
        rng = random.Random(42)
        alphabet = string.ascii_lowercase
        for _ in range(200):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
            c = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
            self.assertLessEqual(levenshtein(a, c), levenshtein(a, b) + levenshtein(b, c))


def _brute_force_within(vocab, word, max_dist):
    return sorted(
        [(w, levenshtein(word, w)) for w in vocab if levenshtein(word, w) <= max_dist],
        key=lambda item: (item[1], item[0]),
    )


class TestBKTree(unittest.TestCase):
    def setUp(self):
        self.vocab = [
            "search", "engine", "index", "query", "spreadsheet", "formula",
            "cache", "hash", "table", "vector", "matrix", "network", "graph",
            "solver", "parser", "lexer", "stemmer", "consensus", "raft",
            "quorum", "chess", "queen", "quench", "quiet", "quilt",
        ]
        self.tree = BKTree()
        self.tree.build(self.vocab)

    def test_matches_brute_force_over_many_queries(self):
        queries = ["serch", "enigne", "spredsheet", "qeury", "consenus", "xyzabc", "queeen"]
        for q in queries:
            for max_dist in (1, 2, 3):
                with self.subTest(query=q, max_dist=max_dist):
                    expected = _brute_force_within(self.vocab, q, max_dist)
                    actual = sorted(self.tree.query(q, max_dist))
                    self.assertEqual(actual, sorted(expected))

    def test_exact_match_has_distance_zero(self):
        results = self.tree.query("search", 0)
        self.assertEqual(results, [("search", 0)])

    def test_no_matches_beyond_threshold(self):
        results = self.tree.query("zzzzzzzzzz", 2)
        self.assertEqual(results, [])

    def test_empty_tree(self):
        empty = BKTree()
        self.assertEqual(empty.query("anything", 5), [])

    def test_duplicate_words_do_not_duplicate_results(self):
        tree = BKTree()
        tree.build(["cat", "cat", "cat", "dog"])
        results = tree.query("cat", 0)
        self.assertEqual(results, [("cat", 0)])


if __name__ == "__main__":
    unittest.main()
