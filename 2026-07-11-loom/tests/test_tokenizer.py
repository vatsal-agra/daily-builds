import os
import tempfile
import unittest

from loom.tokenizer import ByteBPETokenizer


SAMPLE = "the quick brown fox jumps over the lazy dog. " * 30 + "to be or not to be, that is the question."


class TestByteBPETokenizer(unittest.TestCase):
    def test_base_vocab_is_256_bytes(self):
        tok = ByteBPETokenizer()
        self.assertEqual(tok.vocab_size, 256)

    def test_training_grows_vocab(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=50)
        # training can stop before num_merges if no pair repeats anymore;
        # vocab_size must always be exactly 256 + however many merges landed
        self.assertLessEqual(len(tok.merges), 50)
        self.assertGreater(len(tok.merges), 0)
        self.assertEqual(tok.vocab_size, 256 + len(tok.merges))

    def test_round_trip_on_training_text(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=50)
        ids = tok.encode(SAMPLE)
        self.assertEqual(tok.decode(ids), SAMPLE)
        self.assertLess(len(ids), len(SAMPLE.encode("utf-8")))  # BPE should compress

    def test_round_trip_on_unseen_text(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=50)
        unseen = "zzz qqq 12345 !@#$%"
        self.assertEqual(tok.decode(tok.encode(unseen)), unseen)

    def test_round_trip_empty_string(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=20)
        self.assertEqual(tok.encode(""), [])
        self.assertEqual(tok.decode([]), "")

    def test_round_trip_full_character_range(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=20)
        # includes ASCII control chars, punctuation, and Latin Extended-A
        full_range_text = "".join(chr(c) for c in range(0, 0x250))
        self.assertEqual(tok.decode(tok.encode(full_range_text)), full_range_text)

    def test_round_trip_unicode(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=30)
        text = "unicode: héllo wörld 日本語 🎉 — em dash"
        self.assertEqual(tok.decode(tok.encode(text)), text)

    def test_training_is_deterministic(self):
        tok1, tok2 = ByteBPETokenizer(), ByteBPETokenizer()
        tok1.train(SAMPLE, num_merges=40)
        tok2.train(SAMPLE, num_merges=40)
        self.assertEqual(tok1.merges, tok2.merges)
        self.assertEqual(tok1.encode(SAMPLE), tok2.encode(SAMPLE))

    def test_training_stops_early_when_no_repeated_pairs(self):
        tok = ByteBPETokenizer()
        tok.train("abcdefg", num_merges=100)  # no repeated adjacent pairs at all
        self.assertEqual(len(tok.merges), 0)

    def test_save_load_round_trip(self):
        tok = ByteBPETokenizer()
        tok.train(SAMPLE, num_merges=40)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            tok.save(path)
            loaded = ByteBPETokenizer.load(path)
        self.assertEqual(loaded.vocab_size, tok.vocab_size)
        self.assertEqual(loaded.encode(SAMPLE), tok.encode(SAMPLE))
        self.assertEqual(loaded.decode(loaded.encode(SAMPLE)), SAMPLE)

    def test_merges_reduce_token_count_progressively(self):
        tok_small = ByteBPETokenizer()
        tok_small.train(SAMPLE, num_merges=5)
        tok_big = ByteBPETokenizer()
        tok_big.train(SAMPLE, num_merges=60)
        self.assertGreater(len(tok_small.encode(SAMPLE)), len(tok_big.encode(SAMPLE)))


if __name__ == "__main__":
    unittest.main()
