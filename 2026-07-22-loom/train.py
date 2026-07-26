#!/usr/bin/env python3
"""Train a Loom model from scratch on a text corpus.

Example:
    python3 train.py --corpus corpus/corpus.txt --steps 2000 --out checkpoints/loom
"""

import argparse
import json
import time

import numpy as np

from loom.tokenizer import BPETokenizer
from loom.data import load_and_split, get_batch
from loom.nn import LoomModel
from loom.optim import Adam, lr_schedule
from loom.autograd import cross_entropy
from loom.checkpoint import save_checkpoint
from loom.generate import generate


def evaluate(model, data_ids, block_size, rng, n_batches=10, batch_size=16):
    losses = []
    for _ in range(n_batches):
        x, y = get_batch(data_ids, batch_size, block_size, rng)
        logits, _ = model.forward(x)
        B, T, V = logits.shape
        loss = cross_entropy(logits.reshape(B * T, V), y.reshape(-1))
        losses.append(loss.item())
    return float(np.mean(losses))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="corpus/corpus.txt")
    ap.add_argument("--out", default="checkpoints/loom")
    ap.add_argument("--vocab-size", type=int, default=512)
    ap.add_argument("--dim", type=int, default=64)
    ap.add_argument("--n-layers", type=int, default=4)
    ap.add_argument("--n-heads", type=int, default=4)
    ap.add_argument("--block-size", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--eval-every", type=int, default=200)
    ap.add_argument("--sample-every", type=int, default=500)
    ap.add_argument("--log-file", default=None)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Training BPE tokenizer (target vocab {args.vocab_size}) on {args.corpus} ...")
    text = open(args.corpus, encoding="utf-8").read()
    tokenizer = BPETokenizer()
    tokenizer.train(text, vocab_size=args.vocab_size)
    print(f"  actual vocab size: {tokenizer.vocab_size}")

    train_ids, val_ids = load_and_split(args.corpus, tokenizer)
    print(f"  train tokens: {len(train_ids)}, val tokens: {len(val_ids)}")
    assert len(train_ids) > args.block_size + 1, "corpus too short for --block-size"

    config = dict(
        vocab_size=tokenizer.vocab_size,
        dim=args.dim,
        n_layers=args.n_layers,
        n_heads=args.n_heads,
        max_seq_len=args.block_size,
        seed=args.seed,
    )
    model = LoomModel(**config)
    print(f"Model: {model.num_params():,} parameters, {args.n_layers} layers, dim={args.dim}, heads={args.n_heads}")

    optimizer = Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    log = []
    t0 = time.time()

    # sample from the untrained model first, so the demo/tests have proof of "before"
    untrained_sample, _ = generate(model, tokenizer, "\n", max_new_tokens=80, temperature=1.0, rng=np.random.default_rng(1))
    print("\n--- sample from UNTRAINED model ---")
    print(repr(untrained_sample))
    print("---\n")

    for step in range(args.steps):
        lr = lr_schedule(step, args.warmup, args.steps, args.lr)
        x, y = get_batch(train_ids, args.batch_size, args.block_size, rng)
        logits, _ = model.forward(x)
        B, T, V = logits.shape
        loss = cross_entropy(logits.reshape(B * T, V), y.reshape(-1))

        optimizer.zero_grad()
        loss.backward()
        optimizer.step(lr=lr)

        if step % args.log_every == 0 or step == args.steps - 1:
            elapsed = time.time() - t0
            entry = {"step": step, "train_loss": loss.item(), "lr": lr, "elapsed_sec": round(elapsed, 1)}
            if step % args.eval_every == 0 or step == args.steps - 1:
                val_loss = evaluate(model, val_ids, args.block_size, rng)
                entry["val_loss"] = val_loss
            log.append(entry)
            msg = f"step {step:5d}/{args.steps}  loss {loss.item():.4f}  lr {lr:.2e}  t {elapsed:6.1f}s"
            if "val_loss" in entry:
                msg += f"  val {entry['val_loss']:.4f}"
            print(msg)

        if args.sample_every and step > 0 and step % args.sample_every == 0:
            sample, _ = generate(model, tokenizer, "\n", max_new_tokens=80, temperature=0.8,
                                  rng=np.random.default_rng(1))
            print(f"  [sample @ step {step}] {sample!r}")

    final_val = evaluate(model, val_ids, args.block_size, rng, n_batches=20)
    trained_sample, _ = generate(model, tokenizer, "\n", max_new_tokens=80, temperature=0.8,
                                  rng=np.random.default_rng(1))
    print("\n--- sample from TRAINED model ---")
    print(repr(trained_sample))
    print("---\n")
    print(f"final val loss: {final_val:.4f}")

    save_checkpoint(args.out, model, tokenizer, config, extra={
        "final_train_loss": loss.item(),
        "final_val_loss": final_val,
        "untrained_sample": untrained_sample,
        "trained_sample": trained_sample,
        "steps": args.steps,
        "train_seconds": round(time.time() - t0, 1),
    })
    print(f"Checkpoint saved to {args.out}.npz / {args.out}.json")

    if args.log_file:
        with open(args.log_file, "w") as f:
            json.dump({"config": config, "args": vars(args), "log": log,
                       "final_val_loss": final_val,
                       "untrained_sample": untrained_sample,
                       "trained_sample": trained_sample}, f, indent=2)
        print(f"Run log saved to {args.log_file}")


if __name__ == "__main__":
    main()
