import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.fuzzy import levenshtein, BKTree


class TestLevenshtein(unittest.TestCase):
    def test_identical_strings(self):
        self.assertEqual(levenshtein("raft", "raft"), 0)

    def test_empty_strings(self):
        self.assertEqual(levenshtein("", ""), 0)
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("abc", ""), 3)

    def test_single_substitution(self):
        self.assertEqual(levenshtein("cat", "cot"), 1)

    def test_single_insertion_deletion(self):
        self.assertEqual(levenshtein("cat", "cats"), 1)
        self.assertEqual(levenshtein("cats", "cat"), 1)

    def test_known_distance(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)

    def test_symmetry(self):
        a, b = "consensus", "consesus"
        self.assertEqual(levenshtein(a, b), levenshtein(b, a))


class TestBKTree(unittest.TestCase):
    def setUp(self):
        self.tree = BKTree(levenshtein)
        for word in ["raft", "consensus", "chess", "bloom", "filter", "transposition"]:
            self.tree.insert(word)

    def test_exact_match_found_at_distance_zero(self):
        results = self.tree.search("chess", 0)
        self.assertEqual(results, [("chess", 0)])

    def test_typo_found_within_distance(self):
        results = self.tree.search("consesus", 2)
        words = {w for w, _ in results}
        self.assertIn("consensus", words)

    def test_no_match_beyond_distance(self):
        results = self.tree.search("zzzzzzzzzz", 2)
        self.assertEqual(results, [])

    def test_empty_tree_returns_empty(self):
        empty = BKTree(levenshtein)
        self.assertEqual(empty.search("anything", 5), [])

    def test_duplicate_insert_is_idempotent(self):
        self.tree.insert("raft")
        self.tree.insert("raft")
        results = self.tree.search("raft", 0)
        self.assertEqual(results, [("raft", 0)])


if __name__ == "__main__":
    unittest.main()
