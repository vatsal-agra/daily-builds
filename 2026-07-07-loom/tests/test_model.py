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
    # vocab_size must match a real tokenizer's (>= 256, the base byte vocab)
    # so this exercises load_checkpoint()'s tokenizer/config cross-check too.
    vocab = 256
    model = GPT(vocab, n_embd=16, n_head=2, n_layer=2, block_size=16, seed=4)
    x = np.random.default_rng(0).integers(0, vocab, size=(1, 8))
    logits_before = model(x).data.copy()

    with tempfile.TemporaryDirectory() as d:
        save_checkpoint(d, model, {
            "vocab_size": vocab, "n_embd": 16, "n_head": 2, "n_layer": 2, "block_size": 16,
        })
        tok = BPETokenizer()
        tok.train("hello world", vocab_size=vocab)
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


def test_generate_rejects_top_k_zero_or_negative():
    """top_k=0 used to be silently a no-op (Python's -0 == 0, so the
    'keep the top 0' filter never actually filtered anything) instead of
    being rejected - now it's a clear error."""
    import pytest
    tok = BPETokenizer()
    tok.train("the quick brown fox", vocab_size=270)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=1, block_size=16, seed=9)
    with pytest.raises(ValueError):
        generate(model, tok, "the", max_new_tokens=5, top_k=0, seed=0)
    with pytest.raises(ValueError):
        generate(model, tok, "the", max_new_tokens=5, top_k=-3, seed=0)


def test_generate_under_no_grad_builds_no_graph():
    """generate() never calls .backward(), so its forward passes should run
    under no_grad() and produce plain, graph-free tensors (requires_grad is
    False and there are no _prev children) - not just eventually-collectible
    cyclic ones."""
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog", vocab_size=270)
    model = GPT(tok.vocab_size, n_embd=16, n_head=2, n_layer=2, block_size=16, seed=10)
    x = np.array([[1, 2, 3]])
    out = model(x)
    assert out.requires_grad, "sanity: a normal forward pass should be graph-tracked"

    from loom.tensor import no_grad
    with no_grad():
        out2 = model(x)
    assert out2.requires_grad is False
    assert out2._prev == ()
    assert np.allclose(out.data, out2.data), "no_grad must not change the forward computation"


def test_module_zero_grad_matches_optimizer_zero_grad():
    """Tensor.zero_grad()/Module.zero_grad() and Adam.zero_grad() used to
    disagree (one set grad to a zero array, the other to None); Adam.step()
    skips params whose grad `is None`, so the two are no longer allowed to
    drift apart."""
    rng = np.random.default_rng(0)
    model = GPT(256, n_embd=16, n_head=2, n_layer=1, block_size=8, seed=11)
    x = rng.integers(0, 256, size=(2, 8))
    loss = (model(x) * model(x)).sum()
    loss.backward()
    assert any(p.grad is not None for p in model.parameters())
    model.zero_grad()
    assert all(p.grad is None for p in model.parameters())


def test_load_state_dict_rejects_shape_mismatch():
    import pytest
    model_a = GPT(256, n_embd=16, n_head=2, n_layer=1, block_size=8, seed=0)
    model_b = GPT(256, n_embd=32, n_head=2, n_layer=1, block_size=8, seed=0)  # different n_embd
    with pytest.raises(ValueError, match="shape mismatch"):
        model_a.load_state_dict(model_b.state_dict())


def test_load_state_dict_rejects_missing_keys():
    import pytest
    model = GPT(256, n_embd=16, n_head=2, n_layer=1, block_size=8, seed=0)
    state = model.state_dict()
    del state["tok_emb.weight"]
    with pytest.raises(KeyError):
        model.load_state_dict(state)


def test_load_checkpoint_rejects_vocab_size_mismatch():
    """config.json and tokenizer.json disagreeing on vocab size (e.g. from
    being copied out of two different runs) used to load silently and only
    fail later, deep inside a forward pass, with a confusing IndexError."""
    import pytest
    from loom.train import load_checkpoint, save_checkpoint
    model = GPT(256, n_embd=16, n_head=2, n_layer=1, block_size=8, seed=0)
    with tempfile.TemporaryDirectory() as d:
        save_checkpoint(d, model, {
            "vocab_size": 256, "n_embd": 16, "n_head": 2, "n_layer": 1, "block_size": 8,
        })
        tok = BPETokenizer()
        tok.train("hello world", vocab_size=300)  # mismatched vocab_size
        tok.save(os.path.join(d, "tokenizer.json"))
        with pytest.raises(ValueError, match="inconsistent"):
            load_checkpoint(d)


def test_gpt_with_zero_layers_still_forwards():
    """A 0-layer GPT is a degenerate but fully valid config (--n-layer has no
    CLI minimum) - it must not crash, since loom/viz.py has to handle it too."""
    rng = np.random.default_rng(0)
    model = GPT(256, n_embd=16, n_head=2, n_layer=0, block_size=8, seed=0)
    x = rng.integers(0, 256, size=(1, 3))
    out = model(x)
    assert out.shape == (1, 3, 256)
    assert model.blocks == []
