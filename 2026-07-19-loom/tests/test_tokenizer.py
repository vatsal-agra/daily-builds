import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.tokenizer import CharTokenizer, BPETokenizer, tokenizer_from_dict


class TestCharTokenizer(unittest.TestCase):
    def test_roundtrip(self):
        text = "hello, world! this is Loom.\n"
        tok = CharTokenizer(text)
        ids = tok.encode(text)
        self.assertEqual(tok.decode(ids), text)

    def test_encode_unknown_char_raises_clear_error(self):
        tok = CharTokenizer("abc")
        with self.assertRaises(ValueError) as ctx:
            tok.encode("abz")
        self.assertIn("z", str(ctx.exception))

    def test_token_str(self):
        tok = CharTokenizer("abc")
        ids = tok.encode("cab")
        self.assertEqual([tok.token_str(i) for i in ids], ["c", "a", "b"])

    def test_vocab_size_matches_unique_chars(self):
        text = "aabbccddeeff"
        tok = CharTokenizer(text)
        self.assertEqual(tok.vocab_size, 6)

    def test_serialization_roundtrip(self):
        text = "the quick brown fox"
        tok = CharTokenizer(text)
        d = tok.to_dict()
        tok2 = CharTokenizer.from_dict(d)
        ids = tok2.encode(text)
        self.assertEqual(tok2.decode(ids), text)
        self.assertEqual(tok2.vocab_size, tok.vocab_size)


class TestBPETokenizer(unittest.TestCase):
    CORPUS = ("the quick brown fox jumps over the lazy dog. " * 20 +
              "the dog barked at the quick fox in the morning light. " * 20)

    def test_roundtrip_after_training(self):
        tok = BPETokenizer()
        tok.train(self.CORPUS, num_merges=50)
        for sample in ["the quick fox", "zzz not in corpus éé", "", "a"]:
            ids = tok.encode(sample)
            self.assertEqual(tok.decode(ids), sample)

    def test_merges_reduce_token_count(self):
        tok = BPETokenizer()
        ids = tok.train(self.CORPUS, num_merges=100)
        raw_bytes = len(self.CORPUS.encode("utf-8"))
        self.assertLess(len(ids), raw_bytes)
        # num_merges is a cap, not a guarantee -- training stops early once
        # no repeated adjacent pair remains in this small corpus.
        self.assertGreater(tok.vocab_size, 256)
        self.assertLessEqual(tok.vocab_size, 356)
        self.assertEqual(tok.vocab_size, 256 + len(tok.merges))

    def test_untrained_tokenizer_is_identity_on_bytes(self):
        tok = BPETokenizer()
        text = "hello"
        ids = tok.encode(text)
        np_ids = list(ids)
        self.assertEqual(np_ids, list(text.encode("utf-8")))
        self.assertEqual(tok.decode(ids), text)

    def test_serialization_roundtrip(self):
        tok = BPETokenizer()
        tok.train(self.CORPUS, num_merges=60)
        d = tok.to_dict()
        tok2 = BPETokenizer.from_dict(d)
        sample = "the quick dog"
        ids = tok2.encode(sample)
        self.assertEqual(tok2.decode(ids), sample)
        self.assertEqual(tok2.vocab_size, tok.vocab_size)
        self.assertEqual(tok2.merges, tok.merges)

    def test_learns_frequent_pair_first(self):
        # "th" is the single most frequent adjacent byte pair in this corpus
        # ("the" appears dozens of times) and must be the very first merge.
        tok = BPETokenizer()
        tok.train(self.CORPUS, num_merges=5)
        first_new_id = 256
        self.assertEqual(tok.vocab[first_new_id], b"th")

    def test_dispatch_by_kind(self):
        char_tok = CharTokenizer("abc")
        bpe_tok = BPETokenizer()
        bpe_tok.train("abcabcabc", num_merges=2)
        self.assertIsInstance(tokenizer_from_dict(char_tok.to_dict()), CharTokenizer)
        self.assertIsInstance(tokenizer_from_dict(bpe_tok.to_dict()), BPETokenizer)
        with self.assertRaises(ValueError):
            tokenizer_from_dict({"kind": "nonsense"})


if __name__ == "__main__":
    unittest.main()
