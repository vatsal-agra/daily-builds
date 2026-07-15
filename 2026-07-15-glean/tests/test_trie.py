import unittest

from glean.index import InvertedIndex
from glean.trie import Trie, build_from_index


class TrieTests(unittest.TestCase):
    def setUp(self):
        self.trie = Trie()
        for word, count in [("cat", 3), ("car", 1), ("cart", 2), ("dog", 5), ("do", 1)]:
            self.trie.insert(word, count)

    def test_contains(self):
        self.assertTrue(self.trie.contains("cat"))
        self.assertFalse(self.trie.contains("ca"))  # prefix only, not inserted as a word
        self.assertFalse(self.trie.contains("catnip"))

    def test_complete_prefix(self):
        results = [w for w, _c in self.trie.complete("ca")]
        self.assertEqual(sorted(results), ["car", "cart", "cat"])

    def test_complete_ranks_by_frequency_then_alpha(self):
        results = self.trie.complete("ca")
        self.assertEqual(results[0], ("cat", 3))  # highest frequency first

    def test_complete_exact_word_prefix_of_another(self):
        results = [w for w, _c in self.trie.complete("do")]
        self.assertEqual(sorted(results), ["do", "dog"])

    def test_complete_unknown_prefix(self):
        self.assertEqual(self.trie.complete("zz"), [])

    def test_complete_respects_limit(self):
        big = Trie()
        for i in range(20):
            big.insert(f"apple{i}", i + 1)
        self.assertEqual(len(big.complete("apple", limit=5)), 5)

    def test_complete_empty_prefix_returns_everything_up_to_limit(self):
        results = self.trie.complete("", limit=100)
        self.assertEqual(len(results), 5)

    def test_insert_accumulates_count(self):
        t = Trie()
        t.insert("word", 2)
        t.insert("word", 3)
        results = t.complete("word")
        self.assertEqual(results, [("word", 5)])


class BuildFromIndexTests(unittest.TestCase):
    def test_builds_real_words_not_stems(self):
        idx = InvertedIndex()
        idx.add_document("T", "running runners run every running morning")
        trie = build_from_index(idx)
        # "running" must survive as itself, not be collapsed to the stem "run".
        self.assertTrue(trie.contains("running"))
        results = dict(trie.complete("run", limit=10))
        self.assertIn("running", results)
        self.assertEqual(results["running"], 2)

    def test_empty_index(self):
        trie = build_from_index(InvertedIndex())
        self.assertEqual(trie.complete("a"), [])

    def test_numbers_excluded(self):
        idx = InvertedIndex()
        idx.add_document("T", "the year 1969 was notable")
        trie = build_from_index(idx)
        self.assertFalse(trie.contains("1969"))


if __name__ == "__main__":
    unittest.main()
