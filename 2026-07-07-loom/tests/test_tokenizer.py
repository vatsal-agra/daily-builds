import os
import tempfile

from loom.tokenizer import BPETokenizer

SAMPLE = (
    "First Citizen:\nBefore we proceed any further, hear me speak.\n\n"
    "All:\nSpeak, speak.\n\nFirst Citizen:\nYou are all resolved rather to die "
    "than to famish?\n"
) * 20


def _trained_tokenizer(vocab_size=300):
    tok = BPETokenizer()
    tok.train(SAMPLE, vocab_size=vocab_size)
    return tok


def test_vocab_size_reached():
    tok = _trained_tokenizer(300)
    assert tok.vocab_size == 300


def test_roundtrip_training_text():
    tok = _trained_tokenizer()
    ids = tok.encode(SAMPLE)
    assert tok.decode(ids) == SAMPLE


def test_roundtrip_unseen_unicode_and_punctuation():
    tok = _trained_tokenizer()
    unicode_sample = "unicode: " + chr(0xE9) + "llo w" + chr(0xF6) + "rld " + \
        chr(0x65E5) + chr(0x672C) + chr(0x8A9E) + " emoji " + chr(0x1F389) + chr(0x1F525)
    for text in [
        "Hello, World! 123 !?#@$%",
        unicode_sample,
        "",
        "   \t\nwhitespace\n\t   variety",
        "CamelCase_and_snake_case and kebab-case-words",
        "a" * 500,
    ]:
        ids = tok.encode(text)
        assert tok.decode(ids) == text


def test_compression_below_one_byte_per_token_on_training_text():
    tok = _trained_tokenizer()
    ids = tok.encode(SAMPLE)
    assert len(ids) < len(SAMPLE.encode("utf-8"))


def test_merges_are_learned_in_frequency_order_and_ids_sequential():
    tok = _trained_tokenizer(300)
    assert len(tok.merges) == 300 - 256
    for i, pair in enumerate(tok.merges):
        expected_bytes = tok.vocab_bytes[pair[0]] + tok.vocab_bytes[pair[1]]
        assert tok.vocab_bytes[256 + i] == expected_bytes


def test_save_load_roundtrip():
    tok = _trained_tokenizer()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tok.json")
        tok.save(path)
        loaded = BPETokenizer.load(path)
    assert loaded.vocab_size == tok.vocab_size
    assert loaded.merges == tok.merges
    text = "First Citizen: hear me speak!"
    assert loaded.encode(text) == tok.encode(text)
    assert loaded.decode(loaded.encode(text)) == text


def test_no_unknown_token_on_arbitrary_bytes():
    tok = _trained_tokenizer()
    # codepoints that never appear in the training corpus at all
    weird = " " + chr(0x2603) + chr(0x1F600)
    assert tok.decode(tok.encode(weird)) == weird
