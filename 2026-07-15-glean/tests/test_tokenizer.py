import unittest

from glean.tokenizer import (
    _cvc,
    _ends_double_consonant,
    _measure,
    analyze,
    porter_stem,
    tokenize,
)


class MeasureTests(unittest.TestCase):
    def test_paper_examples(self):
        # Exact examples from Porter's 1980 paper, section 2.
        cases = {
            "tr": 0, "ee": 0, "tree": 0, "y": 0, "by": 0,
            "trouble": 1, "oats": 1, "trees": 1, "ivy": 1,
            "troubles": 2, "private": 2, "oaten": 2, "orrery": 2,
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(_measure(word), expected)

    def test_empty(self):
        self.assertEqual(_measure(""), 0)


class HelperTests(unittest.TestCase):
    def test_ends_double_consonant(self):
        self.assertTrue(_ends_double_consonant("hopp"))
        self.assertFalse(_ends_double_consonant("hop"))
        self.assertFalse(_ends_double_consonant("ee"))  # vowels, not consonants
        self.assertFalse(_ends_double_consonant("a"))

    def test_cvc(self):
        self.assertTrue(_cvc("hop"))
        self.assertFalse(_cvc("hoy"))  # ends in a "wxy" letter
        self.assertFalse(_cvc("ee"))   # too short


class StemmerTests(unittest.TestCase):
    def test_step1a_pluralization(self):
        self.assertEqual(porter_stem("caresses"), "caress")
        self.assertEqual(porter_stem("ponies"), "poni")
        self.assertEqual(porter_stem("ties"), "ti")
        self.assertEqual(porter_stem("caress"), "caress")
        self.assertEqual(porter_stem("cats"), "cat")

    def test_step1b_ed_ing(self):
        self.assertEqual(porter_stem("feed"), "feed")
        self.assertEqual(porter_stem("plastered"), "plaster")
        self.assertEqual(porter_stem("bled"), "bled")
        self.assertEqual(porter_stem("motoring"), "motor")
        self.assertEqual(porter_stem("sing"), "sing")
        self.assertEqual(porter_stem("hopping"), "hop")
        self.assertEqual(porter_stem("tanned"), "tan")
        self.assertEqual(porter_stem("falling"), "fall")
        self.assertEqual(porter_stem("hissing"), "hiss")
        self.assertEqual(porter_stem("fizzed"), "fizz")
        self.assertEqual(porter_stem("filing"), "file")

    def test_step1c_y_to_i(self):
        self.assertEqual(porter_stem("happy"), "happi")
        self.assertEqual(porter_stem("sky"), "sky")

    def test_common_words(self):
        self.assertEqual(porter_stem("running"), "run")
        self.assertEqual(porter_stem("denied"), "deni")
        self.assertEqual(porter_stem("flies"), "fli")
        self.assertEqual(porter_stem("national"), "nation")
        self.assertEqual(porter_stem("connect"), "connect")
        self.assertEqual(porter_stem("connected"), "connect")
        self.assertEqual(porter_stem("connecting"), "connect")
        self.assertEqual(porter_stem("connection"), "connect")
        self.assertEqual(porter_stem("connections"), "connect")

    def test_short_words_left_alone(self):
        self.assertEqual(porter_stem("a"), "a")
        self.assertEqual(porter_stem("is"), "is")
        self.assertEqual(porter_stem("42"), "42")

    def test_non_alpha_untouched(self):
        self.assertEqual(porter_stem("2024"), "2024")

    def test_idempotent_on_curated_words(self):
        words = [
            "running", "flies", "national", "generalization", "reference",
            "compiler", "indexing", "argument", "beautiful", "happiness",
            "organization", "relational", "photosynthesis", "earthquake",
        ]
        for w in words:
            once = porter_stem(w)
            twice = porter_stem(once)
            with self.subTest(word=w):
                self.assertEqual(once, twice, f"not idempotent: {w} -> {once} -> {twice}")

    def test_never_lengthens_much(self):
        # Porter only ever appends a single trailing e/i, never grows a word
        # by more than one character.
        import random
        rng = random.Random(1234)
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        for _ in range(500):
            length = rng.randint(1, 12)
            word = "".join(rng.choice(alphabet) for _ in range(length))
            stemmed = porter_stem(word)
            self.assertLessEqual(len(stemmed), len(word) + 1)


class TokenizeTests(unittest.TestCase):
    def test_offsets_round_trip(self):
        text = "Hello, World! 123 test-case."
        tokens = list(tokenize(text))
        for raw, start, end in tokens:
            self.assertEqual(text[start:end].lower(), raw)

    def test_splits_on_hyphen(self):
        tokens = [t[0] for t in tokenize("test-case")]
        self.assertEqual(tokens, ["test", "case"])

    def test_unicode_word(self):
        tokens = [t[0] for t in tokenize("café naïve")]
        self.assertEqual(tokens, ["café", "naïve"])

    def test_empty_text(self):
        self.assertEqual(list(tokenize("")), [])

    def test_numbers_not_stemmed(self):
        analyzed = analyze("There were 1969 astronauts.")
        terms = [t.term for t in analyzed]
        self.assertIn("1969", terms)

    def test_stopword_flag(self):
        analyzed = analyze("the quick fox")
        flags = {t.raw: t.is_stopword for t in analyzed}
        self.assertTrue(flags["the"])
        self.assertFalse(flags["quick"])
        self.assertFalse(flags["fox"])


if __name__ == "__main__":
    unittest.main()
