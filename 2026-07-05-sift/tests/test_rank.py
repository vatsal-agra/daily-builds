import random
import unittest

from sift.index import InvertedIndex
from sift.rank import bm25_term_score, bruteforce_bm25, idf


DOCS = [
    "the quick brown fox jumps over the lazy dog",
    "a quick fox is not a lazy dog it runs fast through the forest",
    "cooking recipes for baking bread and cakes require careful timing",
    "the fox and the dog became unlikely friends in the forest story",
    "bread baking requires yeast flour water and salt in careful proportion",
    "quantum mechanics describes particles as waves until measured",
    "the quick fox outruns every dog in the annual forest race",
    "salt and yeast are both essential ingredients in careful bread baking",
]


class TestBM25Formula(unittest.TestCase):
    def test_idf_decreases_as_df_increases(self):
        vals = [idf(100, df) for df in [1, 5, 20, 50, 99]]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_idf_nonnegative_even_when_df_exceeds_half_corpus(self):
        # classic BM25 idf can go negative for very common terms; the
        # Lucene-style "+1 inside the log" variant we use never does.
        self.assertGreaterEqual(idf(10, 9), 0.0)
        self.assertGreaterEqual(idf(1000, 999), 0.0)

    def test_higher_tf_scores_higher(self):
        low = bm25_term_score(tf=1, df=5, doc_len=50, avg_doc_len=50, doc_count=100)
        high = bm25_term_score(tf=10, df=5, doc_len=50, avg_doc_len=50, doc_count=100)
        self.assertGreater(high, low)

    def test_tf_zero_scores_zero(self):
        self.assertEqual(bm25_term_score(tf=0, df=5, doc_len=50, avg_doc_len=50, doc_count=100), 0.0)

    def test_longer_document_penalized_for_same_tf(self):
        short_doc = bm25_term_score(tf=2, df=5, doc_len=20, avg_doc_len=50, doc_count=100)
        long_doc = bm25_term_score(tf=2, df=5, doc_len=200, avg_doc_len=50, doc_count=100)
        self.assertGreater(short_doc, long_doc)

    def test_b_zero_removes_length_normalization(self):
        short_doc = bm25_term_score(tf=2, df=5, doc_len=20, avg_doc_len=50, doc_count=100, b=0.0)
        long_doc = bm25_term_score(tf=2, df=5, doc_len=200, avg_doc_len=50, doc_count=100, b=0.0)
        self.assertAlmostEqual(short_doc, long_doc)


class TestIndexedVsBruteForceBM25(unittest.TestCase):
    """The indexed BM25 path must agree exactly with an independent
    from-scratch recomputation over the raw corpus text."""

    def setUp(self):
        self.index = InvertedIndex()
        for i, text in enumerate(DOCS):
            self.index.add_document(f"doc{i}.txt", f"Doc {i}", text)

    def _indexed_score(self, terms, doc_id):
        total = 0.0
        for term in terms:
            tf = self.index.term_freq(term, doc_id)
            if tf == 0:
                continue
            df = self.index.doc_freq(term)
            doc = self.index.documents[doc_id]
            total += bm25_term_score(
                tf, df, doc.length, self.index.avg_doc_length, self.index.doc_count
            )
        return total

    def test_agreement_across_all_docs_and_several_queries(self):
        queries = [["fox"], ["dog", "fox"], ["bread", "bake", "salt"], ["forest"], ["quantum"]]
        for terms in queries:
            for doc_id in range(len(DOCS)):
                indexed = self._indexed_score(terms, doc_id)
                brute = bruteforce_bm25(DOCS, terms, doc_id)
                self.assertAlmostEqual(
                    indexed, brute, places=9,
                    msg=f"terms={terms} doc={doc_id}: indexed={indexed} brute={brute}",
                )

    def test_agreement_with_random_term_subsets(self):
        rng = random.Random(42)
        vocab = self.index.vocabulary()
        for _ in range(30):
            k = rng.randint(1, 4)
            terms = rng.sample(vocab, k)
            doc_id = rng.randrange(len(DOCS))
            indexed = self._indexed_score(terms, doc_id)
            brute = bruteforce_bm25(DOCS, terms, doc_id)
            self.assertAlmostEqual(indexed, brute, places=9)


if __name__ == "__main__":
    unittest.main()
