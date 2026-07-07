import os
import tempfile

import numpy as np

from loom.data import Dataset
from loom.functional import cross_entropy
from loom.generate import generate
from loom.nn import GPT
from loom.optim import Adam
from loom.tokenizer import BPETokenizer
from loom.train import load_checkpoint, save_checkpoint


def test_overfit_tiny_batch_drives_loss_to_near_zero():
    """The standard ML-engineering proof that forward + backward + optimizer
    are wired together correctly: a model that can't memorize four length-8
    sequences after 200 steps has a real bug somewhere in the graph."""
    rng = np.random.default_rng(0)
    vocab = 20
    model = GPT(vocab, n_embd=32, n_head=4, n_layer=2, block_size=8, seed=1)
    opt = Adam(model.parameters(), lr=3e-3)

    x = rng.integers(0, vocab, size=(4, 8))
    y = rng.integers(0, vocab, size=(4, 8))

    losses = []
    for _ in range(200):
        logits = model(x)
        loss = cross_entropy(logits.reshape(-1, vocab), y.reshape(-1))
        opt.zero_grad()
        loss.backward()
        opt.clip_grad_norm(1.0)
        opt.step()
        losses.append(loss.item())

    assert losses[0] > 2.0, "sanity: initial loss should reflect near-random predictions"
    assert losses[-1] < 0.05, f"failed to overfit a tiny batch, final loss={losses[-1]}"
    assert losses[-1] < losses[0] / 20


def test_causal_mask_position_i_ignores_future_tokens():
    """Changing token T-1 must not change the model's output at any position
    < T-1 (that would be information leaking from the future)."""
    rng = np.random.default_rng(0)
    vocab = 30
    model = GPT(vocab, n_embd=16, n_head=2, n_layer=2, block_size=16, seed=2)

    ids = rng.integers(0, vocab, size=(1, 10))
    out1 = model(ids).data.copy()

    ids2 = ids.copy()
    ids2[0, -1] = (ids2[0, -1] + 1) % vocab
    out2 = model(ids2).data.copy()

    assert np.allclose(out1[:, :-1], out2[:, :-1], atol=1e-9), \
        "output at earlier positions changed when only the last token changed"
    assert not np.allclose(out1[:, -1], out2[:, -1]), \
        "changing the last input token should change its own output logits"


def test_causal_mask_matches_prefix_when_extended():
    """Running a short sequence and a longer sequence that starts with the
    same prefix must give identical logits on the shared prefix (this is
    what makes autoregressive generation with a growing context valid)."""
    rng = np.random.default_rng(0)
    vocab = 30
    model = GPT(vocab, n_embd=16, n_head=2, n_layer=2, block_size=16, seed=3)

    prefix = rng.integers(0, vocab, size=(1, 5))
    extra = rng.integers(0, vocab, size=(1, 3))
    full = np.concatenate([prefix, extra], axis=1)

    out_prefix = model(prefix).data
    out_full = model(full).data

    assert np.allclose(out_prefix, out_full[:, :5], atol=1e-9)


def test_dataset_batches_are_shifted_by_one():
    ids = np.arange(1000)
    ds = Dataset(ids, val_fraction=0.1)
    rng = np.random.default_rng(0)
    x, y = ds.get_batch("train", batch_size=4, block_size=16, rng=rng)
    assert x.shape == (4, 16)
    assert y.shape == (4, 16)
    assert np.array_equal(x[:, 1:], y[:, :-1])


def test_checkpoint_roundtrip_reproduces_logits():
    vocab = 40
    model = GPT(vocab, n_embd=16, n_head=2, n_layer=2, block_size=16, seed=4)
    x = np.random.default_rng(0).integers(0, vocab, size=(1, 8))
    logits_before = model(x).data.copy()

    with tempfile.TemporaryDirectory() as d:
        save_checkpoint(d, model, {
            "vocab_size": vocab, "n_embd": 16, "n_head": 2, "n_layer": 2, "block_size": 16,
        })
        tok = BPETokenizer()
        tok.train("hello world", vocab_size=256)
        tok.save(os.path.join(d, "tokenizer.json"))
        loaded_model, loaded_tok, config = load_checkpoint(d)

    logits_after = loaded_model(x).data
    assert np.allclose(logits_before, logits_after, atol=1e-9)


def test_generate_produces_requested_length_and_valid_text():
    tok = BPETokenizer()
    tok.train("hello world, this is loom, a tiny llm built from scratch.", vocab_size=280)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=2, block_size=32, seed=5)

    out_greedy = generate(model, tok, "hello", max_new_tokens=15, greedy=True)
    assert isinstance(out_greedy, str)
    assert out_greedy.startswith("hello")

    out_sampled = generate(model, tok, "hello", max_new_tokens=15, temperature=0.9,
                            top_k=10, seed=0)
    assert isinstance(out_sampled, str)

    out_nucleus = generate(model, tok, "hello", max_new_tokens=15, temperature=1.0,
                            top_p=0.9, seed=0)
    assert isinstance(out_nucleus, str)


def test_generate_is_deterministic_with_fixed_seed():
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog " * 5, vocab_size=280)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=2, block_size=32, seed=6)

    a = generate(model, tok, "the", max_new_tokens=20, temperature=1.0, top_k=5, seed=123)
    b = generate(model, tok, "the", max_new_tokens=20, temperature=1.0, top_k=5, seed=123)
    assert a == b


def test_generate_handles_empty_prompt():
    tok = BPETokenizer()
    tok.train("the quick brown fox", vocab_size=270)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=1, block_size=16, seed=7)
    out = generate(model, tok, "", max_new_tokens=5, seed=0)
    assert isinstance(out, str)


def test_generate_respects_block_size_beyond_context():
    """Prompts/generations longer than block_size must not crash - the
    sliding window in generate() should just use the last block_size tokens."""
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog " * 10, vocab_size=280)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=2, block_size=8, seed=8)
    out = generate(model, tok, "the quick brown fox jumps over the lazy dog", max_new_tokens=30, seed=0)
    assert isinstance(out, str) and len(out) > 0
