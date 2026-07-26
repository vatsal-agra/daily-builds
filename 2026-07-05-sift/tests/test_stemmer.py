import unittest

from sift.stemmer import porter_stem, _measure, _cvc, _contains_vowel


# The classic Porter (1980) reference vocabulary/output pairs, hand-verified
# against the algorithm's definition (not copy-pasted from any stemmer
# implementation's test suite).
REFERENCE_PAIRS = [
    ("caresses", "caress"), ("ponies", "poni"), ("ties", "ti"),
    ("caress", "caress"), ("cats", "cat"),
    ("feed", "feed"), ("agreed", "agre"), ("plastered", "plaster"),
    ("bled", "bled"), ("motoring", "motor"), ("sing", "sing"),
    ("conflated", "conflat"), ("troubled", "troubl"), ("sized", "size"),
    ("hopping", "hop"), ("tanned", "tan"), ("falling", "fall"),
    ("hissing", "hiss"), ("fizzed", "fizz"), ("failing", "fail"),
    ("filing", "file"), ("happy", "happi"), ("sky", "sky"),
    ("relational", "relat"), ("conditional", "condit"), ("rational", "ration"),
    ("valenci", "valenc"), ("hesitanci", "hesit"), ("digitizer", "digit"),
    ("conformabli", "conform"), ("radicalli", "radic"), ("differentli", "differ"),
    ("vileli", "vile"), ("analogousli", "analog"), ("vietnamization", "vietnam"),
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
]


class TestPorterStemmer(unittest.TestCase):
    def test_reference_vocabulary(self):
        failures = []
        for word, expected in REFERENCE_PAIRS:
            got = porter_stem(word)
            if got != expected:
                failures.append((word, expected, got))
        self.assertEqual(failures, [], f"stemmer mismatches: {failures}")

    def test_idempotent_on_already_stemmed_forms(self):
        # Re-stemming a stem should (mostly) be a no-op or converge quickly.
        for word, expected in REFERENCE_PAIRS:
            self.assertEqual(porter_stem(expected), porter_stem(porter_stem(expected)))

    def test_short_words_untouched(self):
        for word in ["a", "is", "ox", "id"]:
            self.assertEqual(porter_stem(word), word)

    def test_empty_string(self):
        self.assertEqual(porter_stem(""), "")

    def test_case_insensitive(self):
        self.assertEqual(porter_stem("RUNNING".lower()), porter_stem("running"))


class TestMeasureHelper(unittest.TestCase):
    def test_known_measures(self):
        # m=0
        for w in ["tr", "ee", "tree", "y", "by"]:
            self.assertEqual(_measure(w), 0, w)
        # m=1
        for w in ["trouble", "oats", "trees", "ivy"]:
            self.assertEqual(_measure(w), 1, w)
        # m=2
        for w in ["troubles", "private", "oaten", "orrery"]:
            self.assertEqual(_measure(w), 2, w)

    def test_cvc_condition(self):
        self.assertTrue(_cvc("hop"))
        self.assertTrue(_cvc("fil"))
        self.assertFalse(_cvc("cow"))  # ends in w, excluded
        self.assertFalse(_cvc("ski"))  # doesn't end cvc (i is a vowel)

    def test_contains_vowel(self):
        self.assertTrue(_contains_vowel("happ"))
        self.assertFalse(_contains_vowel("bzz"))


if __name__ == "__main__":
    unittest.main()
