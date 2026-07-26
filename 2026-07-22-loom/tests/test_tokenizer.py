import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.tokenizer import BPETokenizer

CORPUS_PATH = os.path.join(os.path.dirname(__file__), "..", "corpus", "corpus.txt")


def test_roundtrip_on_training_text():
    text = open(CORPUS_PATH, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=400)
    ids = tok.encode(text)
    assert tok.decode(ids) == text
    return True


def test_roundtrip_on_unseen_text():
    text = open(CORPUS_PATH, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=400)
    for sample in [
        "Hello, world! This text was never in the training corpus.",
        "1234567890 !@#$%^&*()",
        "",
        "a",
        "the the the the the the the",
        "\n\n\t  weird whitespace\t\n",
        "emoji test: \U0001F600 \U0001F30D unicode éèê café",
    ]:
        ids = tok.encode(sample)
        assert tok.decode(ids) == sample, f"roundtrip failed for {sample!r}"
    return True


def test_compression_ratio():
    text = open(CORPUS_PATH, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=400)
    ids = tok.encode(text)
    n_bytes = len(text.encode("utf-8"))
    assert len(ids) < n_bytes, "BPE should compress the byte stream (fewer tokens than bytes)"
    return True


def test_merges_are_learned_in_frequency_order_at_least_first_merge():
    # The very first merge must be the single most frequent adjacent byte pair
    # in the raw corpus -- this is the actual definition of BPE.
    text = open(CORPUS_PATH, encoding="utf-8").read()
    ids = list(text.encode("utf-8"))
    counts = BPETokenizer._count_pairs(ids)
    expected_first = max(counts, key=counts.get)

    tok = BPETokenizer()
    tok.train(text, vocab_size=257)
    assert len(tok.merges_list) == 1
    assert tok.merges_list[0] == expected_first
    return True


def test_save_load_roundtrip(tmp_path="/tmp/loom_tok_test.json"):
    text = open(CORPUS_PATH, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=300)
    tok.save(tmp_path)
    tok2 = BPETokenizer.load(tmp_path)
    assert tok.merges_list == tok2.merges_list
    sample = text[:500]
    assert tok.encode(sample) == tok2.encode(sample)
    assert tok2.decode(tok2.encode(sample)) == sample
    os.remove(tmp_path)
    return True


def test_empty_string():
    tok = BPETokenizer()
    tok.train("hello hello hello world", vocab_size=260)
    assert tok.encode("") == []
    assert tok.decode([]) == ""
    return True


def test_vocab_size_never_exceeds_target_when_corpus_is_small():
    # A tiny corpus can run out of repeated pairs before hitting the target
    # vocab size; training must stop gracefully instead of crashing or
    # looping forever.
    tok = BPETokenizer()
    tok.train("ab", vocab_size=1000)
    assert tok.vocab_size <= 1000
    assert tok.decode(tok.encode("ab")) == "ab"
    return True


ALL_TESTS = [
    test_roundtrip_on_training_text,
    test_roundtrip_on_unseen_text,
    test_compression_ratio,
    test_merges_are_learned_in_frequency_order_at_least_first_merge,
    test_save_load_roundtrip,
    test_empty_string,
    test_vocab_size_never_exceeds_target_when_corpus_is_small,
]


def run_all():
    ok = True
    for t in ALL_TESTS:
        try:
            t()
            print(f"[OK] {t.__name__}")
        except Exception as e:
            ok = False
            print(f"[FAIL] {t.__name__}: {e}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
