"""Training loop: forward -> cross-entropy -> backward -> Adam step."""
import gc
import json
import os
import time

import numpy as np

from .data import Dataset
from .functional import cross_entropy
from .nn import GPT
from .optim import Adam, lr_schedule
from .tensor import no_grad
from .tokenizer import BPETokenizer


def train(
    corpus_path,
    out_dir,
    vocab_size=512,
    n_embd=128,
    n_head=4,
    n_layer=4,
    block_size=128,
    batch_size=32,
    steps=2000,
    lr=3e-4,
    warmup_steps=100,
    eval_every=100,
    eval_iters=20,
    grad_clip=1.0,
    seed=0,
    log_fn=print,
):
    if eval_every < 1:
        raise ValueError(f"eval_every must be >= 1, got {eval_every}")
    os.makedirs(out_dir, exist_ok=True)
    text = open(corpus_path, encoding="utf-8").read()

    tok = BPETokenizer()
    log_fn(f"training BPE tokenizer (target vocab={vocab_size})...")
    tok.train(text, vocab_size=vocab_size)
    log_fn(f"tokenizer trained: {tok.vocab_size} tokens")
    tok.save(os.path.join(out_dir, "tokenizer.json"))

    ids = tok.encode(text)
    log_fn(f"corpus: {len(text)} chars -> {len(ids)} tokens "
           f"({len(text) / max(1, len(ids)):.2f} chars/token)")
    ds = Dataset(ids)

    rng = np.random.default_rng(seed)
    model = GPT(tok.vocab_size, n_embd=n_embd, n_head=n_head, n_layer=n_layer,
                block_size=block_size, seed=seed)
    n_params = sum(p.data.size for p in model.parameters())
    log_fn(f"model: {n_layer} layers, {n_head} heads, {n_embd} dim, "
           f"{n_params:,} parameters")

    opt = Adam(model.parameters(), lr=lr)
    history = {"step": [], "train_loss": [], "val_loss": []}

    def eval_loss(split):
        # Evaluation never calls .backward(), so run it under no_grad(): ops
        # skip building a graph entirely, which sidesteps the reference-cycle
        # memory behavior at the source instead of cleaning it up after the
        # fact (see the comment on the training step below).
        losses = []
        with no_grad():
            for _ in range(eval_iters):
                x, y = ds.get_batch(split, batch_size, block_size, rng)
                logits = model(x)
                loss = cross_entropy(logits.reshape(-1, tok.vocab_size), y.reshape(-1))
                losses.append(loss.item())
        return float(np.mean(losses))

    t0 = time.time()
    for step in range(steps):
        cur_lr = lr_schedule(step, warmup_steps, steps, lr)
        x, y = ds.get_batch("train", batch_size, block_size, rng)

        logits = model(x)
        loss = cross_entropy(logits.reshape(-1, tok.vocab_size), y.reshape(-1))

        opt.zero_grad()
        loss.backward()
        opt.clip_grad_norm(grad_clip)
        opt.step(lr=cur_lr)
        train_loss_value = loss.item()

        # Tensor nodes hold closures that capture themselves (a._backward
        # references `a`), so a training step's graph is a reference cycle -
        # plain refcounting won't free it. Collect explicitly each step so
        # peak memory stays bounded instead of growing until Python's
        # automatic collector happens to run.
        del logits, loss, x, y
        gc.collect()

        if step % eval_every == 0 or step == steps - 1:
            val_loss = eval_loss("val")
            history["step"].append(step)
            history["train_loss"].append(train_loss_value)
            history["val_loss"].append(val_loss)
            elapsed = time.time() - t0
            log_fn(f"step {step:5d} | train loss {train_loss_value:.4f} | "
                   f"val loss {val_loss:.4f} | val ppl {np.exp(val_loss):.2f} | "
                   f"lr {cur_lr:.2e} | {elapsed:.1f}s")

    save_checkpoint(out_dir, model, {
        "vocab_size": tok.vocab_size, "n_embd": n_embd, "n_head": n_head,
        "n_layer": n_layer, "block_size": block_size,
    })
    with open(os.path.join(out_dir, "history.json"), "w") as f:
        json.dump(history, f)

    return model, tok, history


def save_checkpoint(out_dir, model, config):
    with open(os.path.join(out_dir, "config.json"), "w") as f:
        json.dump(config, f)
    state = model.state_dict()
    np.savez(os.path.join(out_dir, "weights.npz"), **{
        k.replace(".", "__"): v for k, v in state.items()
    })


def load_checkpoint(out_dir):
    with open(os.path.join(out_dir, "config.json")) as f:
        config = json.load(f)
    model = GPT(config["vocab_size"], n_embd=config["n_embd"], n_head=config["n_head"],
                n_layer=config["n_layer"], block_size=config["block_size"])
    npz = np.load(os.path.join(out_dir, "weights.npz"))
    state = {k.replace("__", "."): npz[k] for k in npz.files}
    model.load_state_dict(state)
    tok = BPETokenizer.load(os.path.join(out_dir, "tokenizer.json"))
    if tok.vocab_size != config["vocab_size"]:
        raise ValueError(
            f"checkpoint at {out_dir!r} is inconsistent: tokenizer.json has "
            f"vocab_size {tok.vocab_size} but config.json says {config['vocab_size']} "
            "(the two files were likely copied from different runs)")
    return model, tok, config
