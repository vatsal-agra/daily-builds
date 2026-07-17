"""Trains Sprout on data/corpus.txt and checkpoints to checkpoints/.

Usage:
    python3 train.py [--steps N] [--vocab-size N] [--quiet]
"""
import argparse
import os
import pickle
import time

import numpy as np

from nn import GPT, cross_entropy_loss
from optim import Adam
from tokenizer import BPETokenizer
from generate import sample

HERE = os.path.dirname(__file__)
CORPUS_PATH = os.path.join(HERE, "data", "corpus.txt")
CKPT_DIR = os.path.join(HERE, "checkpoints")


def get_batch(token_ids, block_size, batch_size, rng):
    n = len(token_ids)
    if n <= block_size:
        raise ValueError(
            f"corpus has only {n} tokens after tokenization, need > block_size={block_size}"
        )
    ix = rng.integers(0, n - block_size - 1, size=batch_size)
    x = np.stack([token_ids[i : i + block_size] for i in ix])
    y = np.stack([token_ids[i + 1 : i + 1 + block_size] for i in ix])
    return x, y


def evaluate(model, token_ids, block_size, batch_size, rng, n_batches=10):
    losses = []
    for _ in range(n_batches):
        x, y = get_batch(token_ids, block_size, batch_size, rng)
        logits = model.forward(x)
        loss, _ = cross_entropy_loss(logits, y)
        losses.append(loss)
    return float(np.mean(losses))


def save_checkpoint(path, model, tokenizer, config, step, history):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    params = {name: p.copy() for name, p, _ in model.parameters()}
    with open(path, "wb") as f:
        pickle.dump(
            {
                "params": params,
                "config": config,
                "step": step,
                "history": history,
                "merges": tokenizer.merges,
                "vocab": tokenizer.vocab,
            },
            f,
        )


def load_checkpoint(path):
    with open(path, "rb") as f:
        data = pickle.load(f)
    config = data["config"]
    model = GPT(**config)
    for name, p, _ in model.parameters():
        p[...] = data["params"][name]
    tok = BPETokenizer()
    tok.merges = data["merges"]
    tok.vocab = data["vocab"]
    return model, tok, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--vocab-size", type=int, default=512)
    ap.add_argument("--block-size", type=int, default=64)
    ap.add_argument("--n-layer", type=int, default=4)
    ap.add_argument("--n-head", type=int, default=4)
    ap.add_argument("--n-embd", type=int, default=128)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--eval-every", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--out", default=os.path.join(CKPT_DIR, "sprout.pkl"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(CORPUS_PATH):
        raise SystemExit(f"corpus not found at {CORPUS_PATH}; run data/make_corpus.py first")

    with open(CORPUS_PATH) as f:
        text = f.read()
    if len(text.strip()) == 0:
        raise SystemExit("corpus.txt is empty")

    np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    tok = BPETokenizer()
    if not args.quiet:
        print(f"training BPE tokenizer to vocab_size={args.vocab_size} on {len(text):,} chars...")
    all_ids = tok.train(text, vocab_size=args.vocab_size, verbose=False)
    token_ids = np.array(all_ids, dtype=np.int64)

    split = int(len(token_ids) * 0.9)
    train_ids, val_ids = token_ids[:split], token_ids[split:]
    if not args.quiet:
        print(
            f"corpus: {len(text):,} chars -> {len(token_ids):,} tokens "
            f"(train={len(train_ids):,}, val={len(val_ids):,}), vocab={tok.vocab_size}"
        )

    config = dict(
        vocab_size=tok.vocab_size,
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
    )
    model = GPT(**config)
    if not args.quiet:
        print(f"model: {model.num_params():,} parameters, config={config}")
    opt = Adam(model, lr=args.lr)

    history = {"step": [], "train_loss": [], "val_loss": []}
    t0 = time.time()
    for step in range(1, args.steps + 1):
        x, y = get_batch(train_ids, args.block_size, args.batch_size, rng)
        model.zero_grad()
        logits = model.forward(x)
        loss, dlogits = cross_entropy_loss(logits, y)
        model.backward(dlogits)
        opt.step(clip_norm=1.0)

        if step % args.eval_every == 0 or step == 1 or step == args.steps:
            val_loss = evaluate(model, val_ids, args.block_size, args.batch_size, rng, n_batches=5)
            history["step"].append(step)
            history["train_loss"].append(float(loss))
            history["val_loss"].append(val_loss)
            if not args.quiet:
                elapsed = time.time() - t0
                sample_ids = sample(
                    model, tok, prompt="", max_new_tokens=60, temperature=0.8, top_k=20, rng=rng
                )
                print(
                    f"step {step:5d}/{args.steps} | train_loss {loss:.3f} | "
                    f"val_loss {val_loss:.3f} | {elapsed:.1f}s"
                )
                print(f"    sample: {sample_ids!r}")

    save_checkpoint(args.out, model, tok, config, args.steps, history)
    if not args.quiet:
        print(f"saved checkpoint to {args.out}")
    return history


if __name__ == "__main__":
    main()
