"""Training loop: encodes the corpus with a from-scratch-trained BPE
tokenizer, then trains the GPT with Adam + cross-entropy on random
context windows, logging loss history and periodically writing a
checkpoint + a generated sample so progress is visible while it runs.
"""
import argparse
import json
import os
import time

import numpy as np

from .checkpoint import save as save_checkpoint
from .model import GPT, GPTConfig
from .optim import Adam
from .tokenizer import BPETokenizer
from .generate import generate_text

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_batch(data, batch_size, block_size, rng):
    n = len(data)
    ix = rng.integers(0, n - block_size - 1, size=batch_size)
    x = np.stack([data[i:i + block_size] for i in ix])
    y = np.stack([data[i + 1:i + block_size + 1] for i in ix])
    return x, y


def estimate_loss(model, data, batch_size, block_size, rng, iters=20):
    losses = []
    for _ in range(iters):
        x, y = get_batch(data, batch_size, block_size, rng)
        _, loss = model(x, y, training=False)
        losses.append(loss.data.item())
    return float(np.mean(losses))


def main():
    ap = argparse.ArgumentParser(description="Train Loom, a from-scratch tiny GPT.")
    ap.add_argument("--corpus", default=os.path.join(HERE, "data", "shakespeare.txt"))
    ap.add_argument("--out", default=os.path.join(HERE, "checkpoints", "loom-shakespeare"))
    ap.add_argument("--vocab-size", type=int, default=512)
    ap.add_argument("--block-size", type=int, default=128)
    ap.add_argument("--n-layer", type=int, default=4)
    ap.add_argument("--n-head", type=int, default=4)
    ap.add_argument("--n-embd", type=int, default=128)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--batch-size", type=int, default=48)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--max-steps", type=int, default=3000)
    ap.add_argument("--eval-interval", type=int, default=200)
    ap.add_argument("--log-interval", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--reuse-tokenizer", action="store_true",
                     help="reuse tokenizer.json in --out if present instead of retraining")
    args = ap.parse_args()

    np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    with open(args.corpus, encoding="utf-8") as f:
        text = f.read()
    print(f"corpus: {len(text)} chars from {args.corpus}")

    os.makedirs(args.out, exist_ok=True)
    tok_path = os.path.join(args.out, "tokenizer.json")
    if args.reuse_tokenizer and os.path.exists(tok_path):
        tokenizer = BPETokenizer.load(tok_path)
        print(f"reusing tokenizer: vocab_size={tokenizer.vocab_size}")
    else:
        t0 = time.time()
        tokenizer = BPETokenizer()
        tokenizer.train(text, args.vocab_size, verbose=True)
        print(f"trained tokenizer: vocab_size={tokenizer.vocab_size} in {time.time()-t0:.1f}s")

    ids = np.array(tokenizer.encode(text), dtype=np.int64)
    n = len(ids)
    split = int(n * 0.9)
    train_data, val_data = ids[:split], ids[split:]
    print(f"tokens: {n} (train {len(train_data)}, val {len(val_data)})")

    cfg = GPTConfig(
        vocab_size=tokenizer.vocab_size,
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
        dropout=args.dropout,
    )
    model = GPT(cfg)
    print(f"model params: {model.num_params():,}")
    print(f"random-init baseline loss ~= ln(vocab_size) = {np.log(cfg.vocab_size):.4f}")

    opt = Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    history = []
    t_start = time.time()
    for step in range(1, args.max_steps + 1):
        x, y = get_batch(train_data, args.batch_size, args.block_size, rng)
        _, loss = model(x, y, training=True)
        opt.zero_grad()
        loss.backward()
        opt.step()

        if step % args.log_interval == 0 or step == 1:
            print(f"step {step:5d}/{args.max_steps}  train_loss {loss.data.item():.4f}  "
                  f"elapsed {time.time()-t_start:.1f}s")

        if step % args.eval_interval == 0 or step == args.max_steps:
            val_loss = estimate_loss(model, val_data, args.batch_size, args.block_size, rng)
            train_loss_avg = estimate_loss(model, train_data, args.batch_size, args.block_size, rng)
            history.append({"step": step, "train_loss": train_loss_avg, "val_loss": val_loss,
                             "elapsed_s": time.time() - t_start})
            print(f"  eval @ step {step}: train {train_loss_avg:.4f}  val {val_loss:.4f}")
            sample = generate_text(model, tokenizer, prompt="\n", max_new_tokens=120,
                                    temperature=0.8, top_k=40, seed=step)
            print(f"  sample: {sample!r}")

            meta = {
                "step": step,
                "max_steps": args.max_steps,
                "config": vars(args),
                "history": history,
                "num_params": model.num_params(),
                "sample": sample,
            }
            save_checkpoint(args.out, model, tokenizer, meta)

    print(f"done in {time.time()-t_start:.1f}s. checkpoint at {args.out}")


if __name__ == "__main__":
    main()
