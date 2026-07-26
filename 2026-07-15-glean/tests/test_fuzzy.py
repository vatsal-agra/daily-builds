import random
import unittest

from glean.fuzzy import BKTree, FuzzyIndex, levenshtein
from glean.index import InvertedIndex


class LevenshteinTests(unittest.TestCase):
    def test_identical_strings(self):
        self.assertEqual(levenshtein("kitten", "kitten"), 0)

    def test_empty_strings(self):
        self.assertEqual(levenshtein("", ""), 0)
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("abc", ""), 3)

    def test_classic_example(self):
        # The textbook kitten/sitting example: substitute k->s, e->i, insert g.
        self.assertEqual(levenshtein("kitten", "sitting"), 3)

    def test_single_substitution(self):
        self.assertEqual(levenshtein("cat", "bat"), 1)

    def test_single_insertion(self):
        self.assertEqual(levenshtein("cat", "cats"), 1)

    def test_symmetry(self):
        rng = random.Random(7)
        alphabet = "abcdefg"
        for _ in range(200):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
            self.assertEqual(levenshtein(a, b), levenshtein(b, a))

    def test_triangle_inequality(self):
        rng = random.Random(99)
        alphabet = "abcd"
        for _ in range(200):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
            c = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
            self.assertLessEqual(levenshtein(a, c), levenshtein(a, b) + levenshtein(b, c))


class BKTreeTests(unittest.TestCase):
    def setUp(self):
        self.words = ["cat", "cats", "bat", "bar", "bare", "hello", "help", "yellow"]
        self.tree = BKTree()
        for w in self.words:
            self.tree.add(w)

    def test_len(self):
        self.assertEqual(len(self.tree), len(self.words))

    def test_exact_match_included(self):
        results = dict(self.tree.search("cat", 0))
        self.assertEqual(results, {"cat": 0})

    def test_bounded_search_matches_brute_force(self):
        query = "cate"
        max_d = 2
        expected = sorted(w for w in self.words if levenshtein(w, query) <= max_d)
        got = sorted(w for w, _d in self.tree.search(query, max_d))
        self.assertEqual(got, expected)

    def test_duplicate_insert_is_noop(self):
        before = len(self.tree)
        self.tree.add("cat")
        self.assertEqual(len(self.tree), before)

    def test_empty_tree(self):
        empty = BKTree()
        self.assertEqual(empty.search("anything", 5), [])

    def test_random_fuzz_matches_brute_force(self):
        rng = random.Random(42)
        alphabet = "abcdefghij"
        words = list({"".join(rng.choice(alphabet) for _ in range(rng.randint(2, 8))) for _ in range(150)})
        tree = BKTree()
        for w in words:
            tree.add(w)
        for _ in range(30):
            query = "".join(rng.choice(alphabet) for _ in range(rng.randint(2, 8)))
            max_d = rng.randint(0, 3)
            expected = sorted(w for w in words if levenshtein(w, query) <= max_d)
            got = sorted(w for w, _d in tree.search(query, max_d))
            self.assertEqual(got, expected, f"mismatch for query={query!r} max_d={max_d}")


class FuzzyIndexTests(unittest.TestCase):
    def test_suggests_close_term(self):
        idx = InvertedIndex()
        idx.add_document("A", "photosynthesis converts sunlight into energy")
        fuzzy = FuzzyIndex(idx)
        suggestions = fuzzy.suggest("photosinthesis", max_distance=3)
        self.assertTrue(any("photosynthesi" in word for word, _d in suggestions))

    def test_no_suggestions_for_wildly_different_term(self):
        idx = InvertedIndex()
        idx.add_document("A", "cat dog bird fish")
        fuzzy = FuzzyIndex(idx)
        self.assertEqual(fuzzy.suggest("xyzxyzxyzxyz", max_distance=2), [])

    def test_empty_index(self):
        fuzzy = FuzzyIndex(InvertedIndex())
        self.assertEqual(fuzzy.suggest("anything"), [])


if __name__ == "__main__":
    unittest.main()
