"""BPE tokenizer: round-trip correctness, determinism, and edge cases."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.tokenizer import BPETokenizer, EOT_ID


def test_round_trip_on_corpus():
    corpus_path = os.path.join(os.path.dirname(__file__), "..", "corpus", "fables.txt")
    text = open(corpus_path, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text[:50000], target_vocab_size=400)

    for sample in [text[:500], text[10000:10800], "", "a", "The quick fox.\n\nAnother line!"]:
        ids = tok.encode(sample)
        assert tok.decode(ids) == sample, f"round trip failed for sample starting {sample[:30]!r}"
    print("  round trip: OK on 5 samples incl. empty string")


def test_eot_not_in_decoded_merges():
    tok = BPETokenizer()
    tok.train("the cat sat on the mat. " * 50, target_vocab_size=300)
    ids = tok.encode("the cat", add_eot=True)
    assert ids[-1] == EOT_ID
    decoded = tok.decode(ids)
    assert decoded == "the cat", f"EOT leaked into decode: {decoded!r}"
    print("  EOT token: encodes at end, excluded from decode")


def test_determinism():
    text = "repeat repeat repeat banana banana apple " * 20
    tok1 = BPETokenizer()
    tok1.train(text, target_vocab_size=280)
    tok2 = BPETokenizer()
    tok2.train(text, target_vocab_size=280)
    assert tok1.merges == tok2.merges, "BPE training is not deterministic"
    print("  determinism: OK (same merges from same corpus)")


def test_save_load(tmp_path="/tmp/loom_tok_test.json"):
    text = "the quick brown fox jumps over the lazy dog. " * 30
    tok = BPETokenizer()
    tok.train(text, target_vocab_size=300)
    tok.save(tmp_path)
    tok2 = BPETokenizer.load(tmp_path)
    sample = "the quick fox"
    assert tok.encode(sample) == tok2.encode(sample)
    assert tok.decode(tok.encode(sample)) == tok2.decode(tok2.encode(sample)) == sample
    print("  save/load: OK")
    os.remove(tmp_path)


def test_unicode_bytes_round_trip():
    tok = BPETokenizer()
    tok.train("café naïve résumé " * 30 + "plain ascii text here " * 30, target_vocab_size=320)
    sample = "café naïve"
    ids = tok.encode(sample)
    assert tok.decode(ids) == sample, "multi-byte UTF-8 characters must round-trip"
    print("  UTF-8 multibyte round trip: OK")


if __name__ == "__main__":
    test_round_trip_on_corpus()
    test_eot_not_in_decoded_merges()
    test_determinism()
    test_save_load()
    test_unicode_bytes_round_trip()
    print("ALL TOKENIZER TESTS PASSED")
