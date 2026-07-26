import unittest

from sift.trie import Trie


class TestTrie(unittest.TestCase):
    def setUp(self):
        self.trie = Trie()
        for w in ["cook", "cooking", "cooked", "cooler", "coral", "run", "runner"]:
            self.trie.insert(w)

    def test_prefix_match(self):
        self.assertEqual(
            self.trie.words_with_prefix("cook"), ["cook", "cooked", "cooking"]
        )

    def test_prefix_excludes_non_matching_branches(self):
        results = self.trie.words_with_prefix("run")
        self.assertEqual(results, ["run", "runner"])
        self.assertNotIn("cook", results)

    def test_unknown_prefix_returns_empty(self):
        self.assertEqual(self.trie.words_with_prefix("zzz"), [])

    def test_empty_prefix_returns_all_words(self):
        results = self.trie.words_with_prefix("")
        self.assertEqual(len(results), 7)

    def test_exact_word_is_prefix_of_itself(self):
        self.assertIn("cook", self.trie.words_with_prefix("cook"))

    def test_shared_prefix_disambiguation(self):
        # "cor" should only reach "coral", not the "cook*" family
        self.assertEqual(self.trie.words_with_prefix("cor"), ["coral"])


if __name__ == "__main__":
    unittest.main()
