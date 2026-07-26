import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.tokenizer import tokenize, normalize_term, STOPWORDS


class TestTokenizer(unittest.TestCase):
    def test_basic_stream(self):
        toks = tokenize("The quick brown fox jumps over the lazy dog.")
        terms = [t.term for t in toks]
        # "the" and "over" are stopwords and must not appear
        self.assertNotIn("the", terms)
        self.assertNotIn("over", terms)
        self.assertIn("quick", terms)
        self.assertIn("fox", terms)
        self.assertIn("lazi", terms)  # "lazy" stemmed

    def test_positions_are_dense_after_stopword_removal(self):
        toks = tokenize("the cat the dog the bird")
        # 3 stopwords removed, 3 content words remain at positions 0,1,2
        self.assertEqual([t.term for t in toks], ["cat", "dog", "bird"])

    def test_never_yields_empty_term(self):
        # "s" alone stems to "" under the faithful Porter algorithm;
        # tokenize() must filter it before it reaches the index.
        toks = tokenize("s a i o u")
        for t in toks:
            self.assertNotEqual(t.term, "")

    def test_raw_offsets_point_back_into_source_text(self):
        text = "Hello searchable world"
        toks = tokenize(text)
        for t in toks:
            self.assertEqual(text[t.start:t.end], t.raw)

    def test_normalize_term_matches_indexing_stem(self):
        toks = tokenize("running quickly")
        self.assertEqual(normalize_term("running"), toks[0].term)

    def test_numbers_pass_through_unstemmed(self):
        toks = tokenize("BM25 uses k1 and b parameters")
        terms = [t.term for t in toks]
        self.assertIn("bm25", terms)
        self.assertIn("k1", terms)

    def test_empty_and_punctuation_only_text(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("... --- !!!"), [])

    def test_stopword_list_is_lowercase_and_nonempty(self):
        self.assertGreater(len(STOPWORDS), 50)
        for w in STOPWORDS:
            self.assertEqual(w, w.lower())


if __name__ == "__main__":
    unittest.main()
