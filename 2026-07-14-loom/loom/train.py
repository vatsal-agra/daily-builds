"""Training loop: minibatched cross-entropy over random contiguous windows of
a tokenized corpus, Adam + warmup/cosine LR schedule + grad-norm clipping,
periodic loss logging and checkpointing.
"""
import json
import os
import time

import numpy as np

from loom.model import TransformerLM
from loom.nn import softmax_cross_entropy
from loom.optim import Adam, clip_grad_norm, lr_schedule
from loom.tokenizer import BPETokenizer


def load_or_train_tokenizer(corpus_text, tokenizer_path, vocab_size, verbose=False):
    if os.path.exists(tokenizer_path):
        tok = BPETokenizer.load(tokenizer_path)
        if tok.vocab_size == vocab_size:
            return tok
    tok = BPETokenizer()
    tok.train(corpus_text, vocab_size=vocab_size, verbose=verbose)
    tok.save(tokenizer_path)
    return tok


def make_batch(ids_array, batch_size, seq_len, rng):
    n = len(ids_array)
    if n <= seq_len + 1:
        raise ValueError(
            f"tokenized corpus has only {n} tokens, need > seq_len+1 ({seq_len + 1})"
        )
    starts = rng.randint(0, n - seq_len - 1, size=batch_size)
    x = np.stack([ids_array[s : s + seq_len] for s in starts])
    y = np.stack([ids_array[s + 1 : s + seq_len + 1] for s in starts])
    return x, y


def train(
    corpus_path,
    out_dir,
    vocab_size=512,
    d_model=128,
    n_heads=4,
    n_layers=4,
    seq_len=128,
    batch_size=32,
    steps=2000,
    lr=3e-4,
    warmup_steps=100,
    weight_decay=0.01,
    grad_clip=1.0,
    seed=0,
    log_every=20,
    ckpt_every=500,
    verbose=True,
):
    if d_model % n_heads != 0:
        raise ValueError("d_model must be divisible by n_heads")

    os.makedirs(out_dir, exist_ok=True)
    with open(corpus_path, encoding="utf-8") as f:
        text = f.read()
    if len(text) == 0:
        raise ValueError(f"corpus at {corpus_path} is empty")

    tokenizer_path = os.path.join(out_dir, "tokenizer.json")
    tok = load_or_train_tokenizer(text, tokenizer_path, vocab_size, verbose=verbose)
    ids = np.array(tok.encode(text), dtype=np.int64)
    if verbose:
        print(f"corpus: {len(text)} chars -> {len(ids)} tokens (vocab={tok.vocab_size})")

    model = TransformerLM(
        vocab_size=tok.vocab_size,
        d_model=d_model,
        n_heads=n_heads,
        n_layers=n_layers,
        max_seq_len=seq_len,
        seed=seed,
    )
    params = model.parameters()
    opt = Adam(params, lr=lr, weight_decay=weight_decay)
    rng = np.random.RandomState(seed + 1)

    log_path = os.path.join(out_dir, "train_log.jsonl")
    log_f = open(log_path, "w")

    t0 = time.time()
    losses = []
    for step in range(steps):
        cur_lr = lr_schedule(step, warmup_steps, steps, lr)
        opt.lr = cur_lr

        x, y = make_batch(ids, batch_size, seq_len, rng)
        logits, _ = model.forward(x)
        loss, dlogits = softmax_cross_entropy(logits, y)

        model.zero_grad()
        model.backward(dlogits)
        grad_norm = clip_grad_norm(params, grad_clip)
        opt.step()

        losses.append(float(loss))
        if step % log_every == 0 or step == steps - 1:
            record = dict(step=step, loss=float(loss), lr=cur_lr, grad_norm=grad_norm,
                          elapsed=time.time() - t0)
            log_f.write(json.dumps(record) + "\n")
            log_f.flush()
            if verbose:
                print(f"step {step:5d}/{steps}  loss {loss:.4f}  lr {cur_lr:.2e}  "
                      f"grad_norm {grad_norm:.2f}  ({record['elapsed']:.1f}s)")

        if (step + 1) % ckpt_every == 0 or step == steps - 1:
            save_checkpoint(model, os.path.join(out_dir, "model.npz"), os.path.join(out_dir, "config.json"))

    log_f.close()
    return model, tok, losses


def save_checkpoint(model, npz_path, config_path):
    np.savez(npz_path, **model.state_dict())
    with open(config_path, "w") as f:
        json.dump(model.config(), f)


def load_checkpoint(npz_path, config_path, seed=0):
    with open(config_path) as f:
        config = json.load(f)
    model = TransformerLM.from_config(config, seed=seed)
    state = np.load(npz_path)
    model.load_state_dict(state)
    return model
