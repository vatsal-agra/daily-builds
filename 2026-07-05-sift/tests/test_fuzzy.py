import random
import string
import unittest

from sift.fuzzy import levenshtein, BKTree, naive_fuzzy_search

VOCAB = [
    "python", "programming", "rover", "rocket", "space", "cooking", "bread",
    "quantum", "quantify", "physics", "chess", "chest", "music", "musical",
    "history", "historic", "genome", "gnome", "coral", "choral", "glacier",
    "glacial", "marathon", "mountain", "fountain", "tennis", "tenant",
]


class TestLevenshtein(unittest.TestCase):
    def test_identical_strings(self):
        self.assertEqual(levenshtein("abc", "abc"), 0)

    def test_empty_strings(self):
        self.assertEqual(levenshtein("", ""), 0)
        self.assertEqual(levenshtein("abc", ""), 3)
        self.assertEqual(levenshtein("", "abc"), 3)

    def test_known_distances(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("flaw", "lawn"), 2)
        self.assertEqual(levenshtein("gumbo", "gambol"), 2)
        self.assertEqual(levenshtein("intention", "execution"), 5)

    def test_symmetry(self):
        rng = random.Random(1)
        alphabet = string.ascii_lowercase
        for _ in range(50):
            a = "".join(rng.choices(alphabet, k=rng.randint(0, 8)))
            b = "".join(rng.choices(alphabet, k=rng.randint(0, 8)))
            self.assertEqual(levenshtein(a, b), levenshtein(b, a))

    def test_triangle_inequality(self):
        rng = random.Random(2)
        alphabet = string.ascii_lowercase
        for _ in range(50):
            a, b, c = (
                "".join(rng.choices(alphabet, k=rng.randint(1, 8))) for _ in range(3)
            )
            self.assertLessEqual(levenshtein(a, c), levenshtein(a, b) + levenshtein(b, c))


class TestBKTreeAgreesWithBruteForce(unittest.TestCase):
    def setUp(self):
        self.tree = BKTree(VOCAB[0])
        for w in VOCAB[1:]:
            self.tree.insert(w)

    def test_exact_match_included(self):
        results = self.tree.query("python", 0)
        self.assertEqual(results, [("python", 0)])

    def test_agrees_with_naive_search_for_many_words_and_radii(self):
        for word in ["pithon", "rocket", "qantum", "chess", "glacer", "xyzxyz"]:
            for radius in [0, 1, 2, 3]:
                bk = sorted(self.tree.query(word, radius))
                naive = sorted(naive_fuzzy_search(VOCAB, word, radius))
                self.assertEqual(bk, naive, f"mismatch for {word!r} radius={radius}")

    def test_no_match_beyond_radius(self):
        self.assertEqual(self.tree.query("zzzzzzzzzzzz", 2), [])

    def test_random_words_against_random_vocab(self):
        rng = random.Random(7)
        alphabet = string.ascii_lowercase
        vocab = list({"".join(rng.choices(alphabet, k=rng.randint(3, 9))) for _ in range(60)})
        tree = BKTree(vocab[0])
        for w in vocab[1:]:
            tree.insert(w)
        for _ in range(20):
            probe = "".join(rng.choices(alphabet, k=rng.randint(3, 9)))
            radius = rng.randint(0, 3)
            bk = sorted(tree.query(probe, radius))
            naive = sorted(naive_fuzzy_search(vocab, probe, radius))
            self.assertEqual(bk, naive)


if __name__ == "__main__":
    unittest.main()
