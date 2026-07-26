"""
Training loop: tokenizes the corpus with a freshly-trained BPE tokenizer,
then trains a GPT with AdamW + grad clipping + warmup/cosine LR, logging
loss and periodically checkpointing (weights + tokenizer + config) so
generate.py / the visualizer can load a trained model.
"""
import argparse
import json
import os
import time

import numpy as np

from .model import GPT, GPTConfig
from .optimizer import AdamW, clip_grad_global_norm, warmup_cosine_lr
from .tokenizer import EOT_ID, BPETokenizer


def build_dataset(corpus_path, tokenizer):
    text = open(corpus_path, encoding="utf-8").read()
    fables = [f for f in text.split("\n\n\n") if f.strip()]
    ids = []
    for fable in fables:
        ids.extend(tokenizer.encode(fable, add_eot=True))
    return np.array(ids, dtype=np.int64)


def get_batch(data, batch_size, block_size, rng):
    max_start = len(data) - block_size - 1
    starts = rng.integers(0, max_start, size=batch_size)
    x = np.stack([data[s:s + block_size] for s in starts])
    y = np.stack([data[s + 1:s + 1 + block_size] for s in starts])
    return x, y


def save_checkpoint(path, model, tokenizer, config, step):
    os.makedirs(path, exist_ok=True)
    np.savez(os.path.join(path, "weights.npz"), **model.params())
    tokenizer.save(os.path.join(path, "tokenizer.json"))
    with open(os.path.join(path, "config.json"), "w") as f:
        json.dump({
            "vocab_size": config.vocab_size,
            "n_ctx": config.n_ctx,
            "n_embd": config.n_embd,
            "n_head": config.n_head,
            "n_layer": config.n_layer,
            "n_hidden": config.n_hidden,
            "step": step,
        }, f, indent=2)


def load_checkpoint(path):
    config_path = os.path.join(path, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"no checkpoint at '{path}' (missing {config_path}). "
            f"Run `python3 -m loom.cli train --ckpt-dir {path}` first."
        )
    with open(config_path) as f:
        cfg_data = json.load(f)
    config = GPTConfig(
        vocab_size=cfg_data["vocab_size"], n_ctx=cfg_data["n_ctx"],
        n_embd=cfg_data["n_embd"], n_head=cfg_data["n_head"],
        n_layer=cfg_data["n_layer"], n_hidden=cfg_data["n_hidden"],
    )
    model = GPT(config, seed=0)
    weights = np.load(os.path.join(path, "weights.npz"))
    model.load_state_dict({k: weights[k] for k in weights.files})
    tokenizer = BPETokenizer.load(os.path.join(path, "tokenizer.json"))
    return model, tokenizer, config, cfg_data["step"]


def train(
    corpus_path="corpus/fables.txt",
    ckpt_dir="checkpoints/loom-small",
    vocab_size=512,
    n_ctx=128,
    n_embd=128,
    n_head=4,
    n_layer=4,
    batch_size=32,
    steps=3000,
    lr=3e-3,
    weight_decay=0.01,
    warmup_steps=100,
    grad_clip=1.0,
    log_every=100,
    ckpt_every=500,
    seed=0,
    log_path=None,
):
    rng_np = np.random.default_rng(seed)
    text = open(corpus_path, encoding="utf-8").read()

    tokenizer = BPETokenizer()
    tokenizer.train(text, target_vocab_size=vocab_size)

    data = build_dataset(corpus_path, tokenizer)
    n_val = max(int(0.05 * len(data)), n_ctx + 2)
    train_data, val_data = data[:-n_val], data[-n_val:]

    config = GPTConfig(
        vocab_size=tokenizer.vocab_size, n_ctx=n_ctx, n_embd=n_embd,
        n_head=n_head, n_layer=n_layer,
    )
    model = GPT(config, seed=seed)
    opt = AdamW(model.params(), lr=lr, weight_decay=weight_decay)

    history = []
    t0 = time.time()
    for step in range(steps):
        cur_lr = warmup_cosine_lr(step, warmup_steps, steps, lr)
        x, y = get_batch(train_data, batch_size, n_ctx, rng_np)
        loss, _ = model.loss(x, y)
        clip_grad_global_norm(model.grads, grad_clip)
        opt.step(model.grads, lr=cur_lr)

        if step % log_every == 0 or step == steps - 1:
            vx, vy = get_batch(val_data, min(batch_size, len(val_data) - n_ctx - 1), n_ctx, rng_np)
            val_loss, _ = model.loss(vx, vy)
            elapsed = time.time() - t0
            entry = {"step": step, "train_loss": float(loss), "val_loss": float(val_loss),
                     "lr": cur_lr, "elapsed_s": elapsed}
            history.append(entry)
            print(f"step {step:5d}/{steps} | train_loss {loss:.4f} | val_loss {val_loss:.4f} "
                  f"| lr {cur_lr:.2e} | {elapsed:.1f}s")

        if ckpt_every and (step > 0 and step % ckpt_every == 0):
            save_checkpoint(ckpt_dir, model, tokenizer, config, step)

    save_checkpoint(ckpt_dir, model, tokenizer, config, steps)
    if log_path:
        with open(log_path, "w") as f:
            json.dump(history, f, indent=2)
    return model, tokenizer, config, history


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus/fables.txt")
    ap.add_argument("--ckpt-dir", default="checkpoints/loom-small")
    ap.add_argument("--vocab-size", type=int, default=512)
    ap.add_argument("--n-ctx", type=int, default=128)
    ap.add_argument("--n-embd", type=int, default=128)
    ap.add_argument("--n-head", type=int, default=4)
    ap.add_argument("--n-layer", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--log-path", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    train(
        corpus_path=args.corpus, ckpt_dir=args.ckpt_dir, vocab_size=args.vocab_size,
        n_ctx=args.n_ctx, n_embd=args.n_embd, n_head=args.n_head, n_layer=args.n_layer,
        batch_size=args.batch_size, steps=args.steps, lr=args.lr, seed=args.seed,
        log_path=args.log_path,
    )


if __name__ == "__main__":
    main()
