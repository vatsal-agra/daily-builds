import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.analyzer import analyze, porter_stem, tokenize, STOPWORDS

# Martin Porter's own published test vocabulary (a representative sample spanning
# every step of the 1980 algorithm) -- the canonical correctness check for a
# from-scratch stemmer implementation.
PORTER_VOCAB = [
    ("caresses", "caress"), ("ponies", "poni"), ("caress", "caress"), ("cats", "cat"),
    ("feed", "feed"), ("agreed", "agre"), ("plastered", "plaster"), ("bled", "bled"),
    ("motoring", "motor"), ("sing", "sing"), ("conflated", "conflat"),
    ("troubled", "troubl"), ("sized", "size"), ("hopping", "hop"), ("tanned", "tan"),
    ("falling", "fall"), ("hissing", "hiss"), ("fizzed", "fizz"), ("failing", "fail"),
    ("filing", "file"), ("happy", "happi"), ("sky", "sky"), ("relational", "relat"),
    ("conditional", "condit"), ("rational", "ration"), ("valenci", "valenc"),
    ("hesitanci", "hesit"), ("digitizer", "digit"), ("conformabli", "conform"),
    ("radicalli", "radic"), ("differentli", "differ"), ("vileli", "vile"),
    ("analogousli", "analog"), ("vietnamization", "vietnam"),
    ("predication", "predic"), ("operator", "oper"), ("feudalism", "feudal"),
    ("decisiveness", "decis"), ("hopefulness", "hope"), ("callousness", "callous"),
    ("formaliti", "formal"), ("sensitiviti", "sensit"), ("sensibiliti", "sensibl"),
    ("triplicate", "triplic"), ("formative", "form"), ("formalize", "formal"),
    ("electriciti", "electr"), ("electrical", "electr"), ("hopeful", "hope"),
    ("goodness", "good"), ("revival", "reviv"), ("allowance", "allow"),
    ("inference", "infer"), ("airliner", "airlin"), ("gyroscopic", "gyroscop"),
    ("adjustable", "adjust"), ("defensible", "defens"), ("irritant", "irrit"),
    ("replacement", "replac"), ("adjustment", "adjust"), ("dependent", "depend"),
    ("adoption", "adopt"), ("homologou", "homolog"), ("communism", "commun"),
    ("activate", "activ"), ("angulariti", "angular"), ("homologous", "homolog"),
    ("effective", "effect"), ("bowdlerize", "bowdler"), ("probate", "probat"),
    ("rate", "rate"), ("cease", "ceas"), ("controll", "control"), ("roll", "roll"),
    ("running", "run"), ("builds", "build"), ("building", "build"),
]


class TestPorterStemmer(unittest.TestCase):
    def test_canonical_vocabulary(self):
        mismatches = []
        for word, expected in PORTER_VOCAB:
            got = porter_stem(word)
            if got != expected:
                mismatches.append((word, expected, got))
        self.assertEqual(mismatches, [], f"{len(mismatches)}/{len(PORTER_VOCAB)} mismatched")

    def test_short_words_returned_unchanged(self):
        self.assertEqual(porter_stem("a"), "a")
        self.assertEqual(porter_stem("is"), "is")
        self.assertEqual(porter_stem(""), "")

    def test_case_folding(self):
        self.assertEqual(porter_stem("RUNNING"), porter_stem("running"))

    def test_idempotent_on_already_stemmed_word(self):
        stem = porter_stem("running")
        self.assertEqual(porter_stem(stem), stem)


class TestTokenize(unittest.TestCase):
    def test_splits_on_punctuation(self):
        tokens = [t for t, _ in tokenize("Hello, world! It's a test-case.")]
        self.assertEqual(tokens, ["hello", "world", "it's", "a", "test", "case"])

    def test_empty_string(self):
        self.assertEqual(list(tokenize("")), [])

    def test_numbers_are_tokens(self):
        tokens = [t for t, _ in tokenize("BM25 uses k1=1.5")]
        self.assertIn("bm25", tokens)
        self.assertIn("k1", tokens)

    def test_offsets_point_into_original_text(self):
        text = "  raft consensus"
        pairs = list(tokenize(text))
        for token, offset in pairs:
            self.assertEqual(text[offset:offset + len(token)].lower(), token)


class TestAnalyze(unittest.TestCase):
    def test_stopwords_removed(self):
        terms = [t for t, _, _ in analyze("the raft is a consensus algorithm")]
        self.assertNotIn("the", terms)
        self.assertNotIn("is", terms)
        self.assertNotIn("a", terms)
        self.assertIn("raft", terms)

    def test_positions_preserve_gaps_across_removed_stopwords(self):
        # "raft" and "algorithm" are 3 tokens apart in the original text (raft, is, a,
        # consensus... no -- pick a simpler case with exactly one stopword between).
        terms = analyze("raft the consensus")
        positions = {t: p for t, p, _ in terms}
        self.assertEqual(positions["raft"], 0)
        self.assertEqual(positions["consensu"], 2)  # position 1 ("the") was removed

    def test_empty_and_all_stopword_input(self):
        self.assertEqual(analyze(""), [])
        self.assertEqual(analyze("the a of"), [])

    def test_no_stopwords_survive_in_default_vocab(self):
        self.assertTrue(STOPWORDS)
        self.assertIn("the", STOPWORDS)


if __name__ == "__main__":
    unittest.main()
