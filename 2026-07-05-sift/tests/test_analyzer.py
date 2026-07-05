import unittest

from sift.analyzer import analyze, tokenize_raw, analyze_query_term, STOPWORDS


class TestTokenizeRaw(unittest.TestCase):
    def test_basic_offsets(self):
        text = "Hello, world!"
        toks = tokenize_raw(text)
        self.assertEqual([t[0] for t in toks], ["Hello", "world"])
        for raw, start, end in toks:
            self.assertEqual(text[start:end], raw)

    def test_unicode_letters(self):
        toks = tokenize_raw("café naïve")
        self.assertEqual([t[0] for t in toks], ["café", "naïve"])

    def test_empty_text(self):
        self.assertEqual(tokenize_raw(""), [])

    def test_numbers_are_tokens(self):
        toks = tokenize_raw("Apollo 11 landed in 1969")
        self.assertIn("11", [t[0] for t in toks])
        self.assertIn("1969", [t[0] for t in toks])


class TestAnalyze(unittest.TestCase):
    def test_stopwords_filtered_but_keep_position(self):
        tokens = analyze("the quick fox")
        terms = [t.term for t in tokens]
        self.assertEqual(terms, [None, "quick", "fox"])
        # positions are raw indices, unaffected by filtering
        self.assertEqual([t.position for t in tokens], [0, 1, 2])

    def test_stemming_applied(self):
        tokens = analyze("running runs runner")
        terms = [t.term for t in tokens]
        self.assertEqual(terms, ["run", "run", "runner"])

    def test_no_stem_option(self):
        tokens = analyze("running", stem=False)
        self.assertEqual(tokens[0].term, "running")

    def test_no_stopword_removal_option(self):
        tokens = analyze("the fox", remove_stopwords=False)
        self.assertEqual([t.term for t in tokens], ["the", "fox"])

    def test_query_term_normalization_matches_index_normalization(self):
        indexed = analyze("Rovers")[0].term
        queried = analyze_query_term("rover")
        # not required to be identical, just both real stems of the family
        self.assertEqual(indexed, "rover")
        self.assertEqual(queried, "rover")

    def test_all_stopwords_in_set_are_lowercase(self):
        for w in STOPWORDS:
            self.assertEqual(w, w.lower())


if __name__ == "__main__":
    unittest.main()
