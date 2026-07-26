import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.tokenizer import BPETokenizer  # noqa: E402


def test_train_and_roundtrip():
    text = "the quick brown fox jumps over the lazy dog. " * 200
    tok = BPETokenizer()
    tok.train(text, vocab_size=280)
    assert tok.vocab_size == 280
    ids = tok.encode(text)
    assert tok.decode(ids) == text
    print("  ok: train + exact round-trip")


def test_compression_beats_byte_level():
    text = "the quick brown fox jumps over the lazy dog. " * 200
    tok = BPETokenizer()
    tok.train(text, vocab_size=300)
    ids = tok.encode(text)
    assert len(ids) < len(text.encode("utf-8")), "BPE should compress a repetitive corpus"
    print(f"  ok: compression {len(text.encode('utf-8'))} bytes -> {len(ids)} tokens")


def test_never_hits_unknown_token():
    tok = BPETokenizer()
    tok.train("hello world, this is a small training corpus for byte pair encoding.", vocab_size=270)
    weird = "\x00\x01 日本語 🚀🚀 " + "z" * 50 + " \n\t"
    ids = tok.encode(weird)
    assert tok.decode(ids) == weird
    print("  ok: arbitrary unseen/unicode text always round-trips (byte fallback)")


def test_empty_string():
    tok = BPETokenizer()
    tok.train("some corpus text here for training merges", vocab_size=260)
    assert tok.encode("") == []
    assert tok.decode([]) == ""
    print("  ok: empty string encode/decode")


def test_save_load_roundtrip(tmp_path=None):
    import tempfile
    text = "to be or not to be, that is the question. " * 100
    tok = BPETokenizer()
    tok.train(text, vocab_size=300)
    ids_before = tok.encode(text)

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tok.json")
        tok.save(path)
        tok2 = BPETokenizer.load(path)
        assert tok2.vocab_size == tok.vocab_size
        ids_after = tok2.encode(text)
        assert ids_before == ids_after
        assert tok2.decode(ids_after) == text
    print("  ok: save/load round-trip preserves merges and encoding")


def test_deterministic_training():
    text = "a rose by any other name would smell as sweet " * 80
    tok1 = BPETokenizer()
    tok1.train(text, vocab_size=290)
    tok2 = BPETokenizer()
    tok2.train(text, vocab_size=290)
    assert tok1.merge_order == tok2.merge_order
    print("  ok: training is deterministic given the same corpus")


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print(f"{fn.__name__}:")
        fn()
    print(f"\nAll {len(fns)} tokenizer test groups passed.")
