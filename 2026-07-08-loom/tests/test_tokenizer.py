import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.tokenizer import BPETokenizer  # noqa: E402

TRAIN_TEXT = (
    "the quick brown fox jumps over the lazy dog. "
    "the dog barks at the fox. the fox runs away quickly. "
    "quick foxes and lazy dogs live in the forest. " * 20
)


class TestBPETokenizer(unittest.TestCase):
    def test_untrained_is_raw_bytes(self):
        tok = BPETokenizer()
        ids = tok.encode("hi")
        self.assertEqual(ids, list("hi".encode("utf-8")))
        self.assertEqual(tok.vocab_size, 256)

    def test_train_reduces_token_count_vs_raw_bytes(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        raw_len = len(TRAIN_TEXT.encode("utf-8"))
        bpe_len = len(tok.encode(TRAIN_TEXT))
        self.assertLess(bpe_len, raw_len)
        self.assertGreater(tok.vocab_size, 256)

    def test_roundtrip_on_training_text(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        ids = tok.encode(TRAIN_TEXT)
        self.assertEqual(tok.decode(ids), TRAIN_TEXT)

    def test_roundtrip_on_unseen_text(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        unseen = "Zebras juggle xylophones under a crimson moon!! 12345 ??"
        ids = tok.encode(unseen)
        self.assertEqual(tok.decode(ids), unseen)

    def test_roundtrip_on_unicode_and_emoji(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        weird = "héllo wörld — 日本語 café naïve résumé 🚀🐍✨ \n\ttab and newline"
        ids = tok.encode(weird)
        self.assertEqual(tok.decode(ids), weird)

    def test_roundtrip_on_empty_string(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        self.assertEqual(tok.decode(tok.encode("")), "")

    def test_merges_are_deterministic(self):
        tok1 = BPETokenizer()
        tok1.train(TRAIN_TEXT, vocab_size=280)
        tok2 = BPETokenizer()
        tok2.train(TRAIN_TEXT, vocab_size=280)
        self.assertEqual(tok1.merge_order, tok2.merge_order)

    def test_save_load_roundtrip(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        ids_before = tok.encode(TRAIN_TEXT)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            tok.save(path)
            tok2 = BPETokenizer()
            tok2.load(path)
        self.assertEqual(tok2.merge_order, tok.merge_order)
        self.assertEqual(tok2.encode(TRAIN_TEXT), ids_before)
        unseen = "brand new sentence not in the corpus"
        self.assertEqual(tok2.decode(tok2.encode(unseen)), unseen)

    def test_vocab_size_never_exceeds_requested(self):
        tok = BPETokenizer()
        tok.train("ab" * 5, vocab_size=1000)  # tiny corpus, can't reach 1000
        self.assertLess(tok.vocab_size, 1000)

    def test_decode_never_crashes_on_invalid_byte_boundaries(self):
        tok = BPETokenizer()
        tok.train(TRAIN_TEXT, vocab_size=300)
        # id 205 (0xCD) alone is a stray UTF-8 continuation-lead byte with no
        # valid follow-up in this sequence -- a real risk when decoding
        # arbitrary/model-sampled ids rather than ids from encode().
        result = tok.decode([205, 32, 32])
        self.assertIn("�", result)

    def test_pair_occurring_once_is_not_merged(self):
        tok = BPETokenizer()
        # "qz" appears exactly once across the whole corpus -> must not merge
        tok.train("qz " + "the cat sat on the mat " * 10, vocab_size=1000)
        self.assertNotIn((ord("q"), ord("z")), tok.merges)


if __name__ == "__main__":
    unittest.main()
