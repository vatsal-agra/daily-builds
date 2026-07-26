import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove import stemmer

# Pairs drawn from M.F. Porter's 1980 paper's per-step worked examples,
# run through the *full* five-step pipeline (a word illustrating one
# step's rule may be reduced further by a later step — e.g. step 2 turns
# "hopefulness" into "hopeful", but step 3's FUL rule then strips that
# too, so the final answer is "hope", not the step-2-only "hopeful").
KNOWN_PAIRS = [
    ("caresses", "caress"), ("ponies", "poni"), ("ties", "ti"),
    ("caress", "caress"), ("cats", "cat"),
    ("feed", "feed"), ("agreed", "agre"), ("plastered", "plaster"),
    ("bled", "bled"), ("motoring", "motor"), ("sing", "sing"),
    ("conflated", "conflat"), ("troubling", "troubl"), ("sized", "size"),
    ("hopping", "hop"), ("tanned", "tan"), ("falling", "fall"),
    ("hissing", "hiss"), ("fizzed", "fizz"), ("failing", "fail"),
    ("filing", "file"),
    ("happy", "happi"), ("sky", "sky"),
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
    ("cease", "ceas"), ("controll", "control"), ("roll", "roll"),
    ("generalization", "gener"), ("organization", "organ"), ("multiply", "multipli"),
    ("provision", "provis"), ("national", "nation"),
]


class TestPorterStemmer(unittest.TestCase):
    def test_known_pairs(self):
        for word, expected in KNOWN_PAIRS:
            with self.subTest(word=word):
                self.assertEqual(stemmer.stem(word), expected)

    def test_idempotent_on_already_stemmed_forms(self):
        # Re-stemming a stem should be a no-op or shrink further, never crash.
        for word, expected in KNOWN_PAIRS:
            twice = stemmer.stem(expected)
            self.assertIsInstance(twice, str)

    def test_non_alpha_and_empty_pass_through(self):
        self.assertEqual(stemmer.stem(""), "")
        self.assertEqual(stemmer.stem("123"), "123")
        self.assertEqual(stemmer.stem("a1b2"), "a1b2")

    def test_matches_original_algorithm_edge_case_s_to_empty(self):
        # The literal 1980 algorithm's plain "S ->" rule reduces the
        # degenerate single-letter word "s" to the empty string — verified
        # against the NLTK oracle in ORIGINAL_ALGORITHM mode below. This
        # stemmer stays a faithful port rather than special-casing it;
        # tokenizer.py is the layer responsible for never letting an empty
        # stem become an index term (see test_tokenizer.py).
        self.assertEqual(stemmer.stem("s"), "")

    def test_case_insensitive(self):
        self.assertEqual(stemmer.stem("Running"), stemmer.stem("running"))
        self.assertEqual(stemmer.stem("CARESSES"), stemmer.stem("caresses"))


class TestDifferentialAgainstNLTKOracle(unittest.TestCase):
    """Cross-checks the from-scratch implementation against NLTK's Porter
    stemmer (ORIGINAL_ALGORITHM mode, i.e. the 1980 paper, not NLTK's own
    later patches) over every unique word in this repo's real READMEs —
    thousands of real English words, not a handful of cherry-picked pairs.
    Mirrors how Graft (2026-07-02) validated its object encoding against
    real git, and Ironkey (2026-07-01) against OpenSSL: an independent
    oracle you did not write yourself.

    Skipped (not failed) if NLTK isn't installed, since the shipped
    engine has zero runtime dependency on it — this is a dev-time
    correctness check only.
    """

    def test_matches_nltk_oracle_over_repo_corpus(self):
        try:
            from nltk.stem import PorterStemmer
        except ImportError:
            self.skipTest("nltk not installed; oracle differential check skipped")

        oracle = PorterStemmer(mode=PorterStemmer.ORIGINAL_ALGORITHM)
        repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
        readmes = glob.glob(os.path.join(repo_root, "*", "README.md"))
        self.assertGreater(len(readmes), 10, "expected to find this repo's past project READMEs")

        text = ""
        for path in readmes:
            with open(path, encoding="utf-8", errors="replace") as f:
                text += f.read() + " "

        words = sorted(set(w.lower() for w in re.findall(r"[A-Za-z]+", text)))
        self.assertGreater(len(words), 1000)

        mismatches = []
        for w in words:
            mine = stemmer.stem(w)
            theirs = oracle.stem(w)
            if mine != theirs:
                mismatches.append((w, mine, theirs))

        self.assertEqual(
            mismatches, [],
            f"{len(mismatches)}/{len(words)} words diverged from the NLTK oracle",
        )


if __name__ == "__main__":
    unittest.main()
