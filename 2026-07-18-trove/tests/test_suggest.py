import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.suggest import Trie, build_trie
from trove.index import InvertedIndex


class TestTrie(unittest.TestCase):
    def setUp(self):
        self.trie = Trie()
        for word, freq in [("cat", 5), ("car", 3), ("cart", 1), ("dog", 4), ("do", 2)]:
            self.trie.insert(word, freq)

    def test_suggest_prefix_matches_only(self):
        results = [w for w, _ in self.trie.suggest("ca")]
        self.assertEqual(set(results), {"cat", "car", "cart"})

    def test_suggest_ranked_by_frequency_desc(self):
        results = [w for w, _ in self.trie.suggest("ca")]
        self.assertEqual(results[0], "cat")  # freq 5, highest

    def test_suggest_respects_limit(self):
        results = self.trie.suggest("ca", limit=1)
        self.assertEqual(len(results), 1)

    def test_suggest_no_match_returns_empty(self):
        self.assertEqual(self.trie.suggest("xyz"), [])

    def test_suggest_empty_prefix_returns_empty(self):
        self.assertEqual(self.trie.suggest(""), [])

    def test_prefix_is_itself_a_word(self):
        # "do" is both a complete word and a prefix of "dog"
        results = [w for w, _ in self.trie.suggest("do")]
        self.assertEqual(set(results), {"do", "dog"})

    def test_prefix_matches_matches_suggest_word_set(self):
        self.assertEqual(set(self.trie.prefix_matches("ca")), {"cat", "car", "cart"})

    def test_case_insensitive_lookup(self):
        results = [w for w, _ in self.trie.suggest("CA")]
        self.assertEqual(set(results), {"cat", "car", "cart"})


class TestBuildTrie(unittest.TestCase):
    def test_built_from_index_vocabulary(self):
        idx = InvertedIndex()
        idx.add_document("a", "search engine indexing")
        idx.add_document("b", "search algorithm ranking")
        idx.finalize()
        trie = build_trie(idx)
        results = [w for w, _ in trie.suggest("sear")]
        self.assertIn("search", results)

    def test_frequency_reflects_document_frequency(self):
        idx = InvertedIndex()
        idx.add_document("a", "search")
        idx.add_document("b", "search")
        idx.add_document("c", "sear")  # different stem branch, doc freq 1
        idx.finalize()
        trie = build_trie(idx)
        results = trie.suggest("sea")
        freqs = dict(results)
        self.assertEqual(freqs["search"], 2)


if __name__ == "__main__":
    unittest.main()
