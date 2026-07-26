import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.tokenizer import BPETokenizer


CORPUS = (
    "First Citizen:\nBefore we proceed any further, hear me speak.\n\n"
    "All:\nSpeak, speak.\n\nFirst Citizen:\nYou are all resolved rather to die "
    "than to famish?\n\nAll:\nResolved. resolved.\n" * 20
)


class TestBPETokenizer(unittest.TestCase):
    def test_base_vocab_is_256_bytes(self):
        tok = BPETokenizer()
        self.assertEqual(tok.vocab_size, 256)
        for i in range(256):
            self.assertEqual(tok.id_to_bytes[i], bytes([i]))

    def test_train_grows_vocab_by_requested_merges(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=300)
        self.assertEqual(tok.vocab_size, 300)
        self.assertEqual(len(tok.merges), 44)

    def test_roundtrip_on_training_text(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=300)
        ids = tok.encode(CORPUS)
        self.assertEqual(tok.decode(ids), CORPUS)

    def test_roundtrip_on_unseen_text(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=300)
        unseen = "Zzyx: qwfp 12345 !!! \t\n éè emoji \U0001F600 done."
        ids = tok.encode(unseen)
        self.assertEqual(tok.decode(ids), unseen)

    def test_roundtrip_fuzz_random_bytes(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=280)
        rng = random.Random(42)
        for _ in range(200):
            n = rng.randint(0, 40)
            raw = bytes(rng.randrange(256) for _ in range(n))
            text = raw.decode("utf-8", errors="replace")
            # re-derive from the (possibly lossy) decoded text, since encode()
            # operates on str; the guarantee is round-trip of *valid* text.
            ids = tok.encode(text)
            self.assertEqual(tok.decode(ids), text)

    def test_empty_string(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=280)
        self.assertEqual(tok.encode(""), [])
        self.assertEqual(tok.decode([]), "")

    def test_vocab_size_below_256_rejected(self):
        tok = BPETokenizer()
        with self.assertRaises(ValueError):
            tok.train(CORPUS, vocab_size=100)

    def test_save_load_roundtrip(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=300)
        path = "/tmp/loom_test_tokenizer.json"
        tok.save(path)
        loaded = BPETokenizer.load(path)
        self.assertEqual(loaded.vocab_size, tok.vocab_size)
        sample = "First Citizen: Resolved, resolved!"
        self.assertEqual(loaded.encode(sample), tok.encode(sample))
        self.assertEqual(loaded.decode(tok.encode(sample)), sample)

    def test_compression_beats_raw_bytes(self):
        tok = BPETokenizer()
        tok.train(CORPUS, vocab_size=350)
        ids = tok.encode(CORPUS)
        self.assertLess(len(ids), len(CORPUS.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
