"""Training loop: minibatched next-token prediction over an encoded corpus,
Adam + LR warmup/cosine-decay + global-norm gradient clipping, checkpointing.
"""
import argparse
import json
import os
import time

import numpy as np

from .checkpoint import save_checkpoint
from .nn import GPT
from .optim import Adam, clip_grad_norm, lr_schedule
from .tensor import no_grad
from .tokenizer import BPETokenizer


def get_batch(ids, block_size, batch_size, rng):
    max_start = len(ids) - block_size - 1
    if max_start < 1:
        raise ValueError(
            f"corpus (len={len(ids)} tokens) is too short for block_size={block_size}"
        )
    starts = rng.integers(0, max_start, size=batch_size)
    x = np.stack([ids[s:s + block_size] for s in starts])
    y = np.stack([ids[s + 1:s + block_size + 1] for s in starts])
    return x, y


def estimate_loss(model, ids, block_size, batch_size, iters, rng):
    losses = []
    with no_grad():
        for _ in range(iters):
            x, y = get_batch(ids, block_size, batch_size, rng)
            _, loss = model(x, targets=y)
            losses.append(loss.item())
    return float(np.mean(losses))


def build_argparser():
    p = argparse.ArgumentParser(description="Train a from-scratch GPT on a text corpus.")
    p.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "..", "data", "corpus.txt"))
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "checkpoints"))
    p.add_argument("--vocab-size", type=int, default=512)
    p.add_argument("--n-embd", type=int, default=128)
    p.add_argument("--n-head", type=int, default=4)
    p.add_argument("--n-layer", type=int, default=4)
    p.add_argument("--block-size", type=int, default=128)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--warmup-steps", type=int, default=100)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--eval-every", type=int, default=200)
    p.add_argument("--eval-iters", type=int, default=20)
    p.add_argument("--log-every", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    return p


def train(args):
    rng = np.random.default_rng(args.seed)

    with open(args.corpus) as f:
        text = f.read()

    tok = BPETokenizer()
    tok.train(text, vocab_size=args.vocab_size, verbose=False)
    ids = np.array(tok.encode(text), dtype=np.int64)
    print(f"corpus: {len(text)} chars -> {len(ids)} tokens, vocab_size={tok.vocab_size}")

    split = int(len(ids) * (1 - args.val_frac))
    train_ids, val_ids = ids[:split], ids[split:]
    if len(val_ids) <= args.block_size:
        raise ValueError(
            "validation split is shorter than block_size; use a longer corpus, "
            "a smaller block_size, or a smaller --val-frac"
        )

    model = GPT(
        vocab_size=tok.vocab_size,
        n_embd=args.n_embd,
        n_head=args.n_head,
        n_layer=args.n_layer,
        block_size=args.block_size,
    )
    print(f"model: {model.num_params():,} parameters")

    opt = Adam(model.parameters(), lr=args.lr)

    os.makedirs(args.out_dir, exist_ok=True)
    history = []
    t0 = time.time()
    for step in range(args.steps):
        lr = lr_schedule(step, args.warmup_steps, args.steps, args.lr)
        opt.lr = lr

        x, y = get_batch(train_ids, args.block_size, args.batch_size, rng)
        _, loss = model(x, targets=y)

        opt.zero_grad()
        loss.backward()
        grad_norm = clip_grad_norm(model.parameters(), args.grad_clip)
        opt.step()

        if step % args.log_every == 0 or step == args.steps - 1:
            elapsed = time.time() - t0
            print(
                f"step {step:5d} | loss {loss.item():.4f} | lr {lr:.2e} | "
                f"grad_norm {grad_norm:.2f} | {elapsed:.1f}s"
            )

        if step % args.eval_every == 0 or step == args.steps - 1:
            val_loss = estimate_loss(
                model, val_ids, args.block_size, args.batch_size, args.eval_iters, rng
            )
            train_loss = estimate_loss(
                model, train_ids, args.block_size, args.batch_size, args.eval_iters, rng
            )
            history.append({"step": step, "train_loss": train_loss, "val_loss": val_loss})
            print(f"          eval: train_loss {train_loss:.4f} | val_loss {val_loss:.4f}")

    weights_path = os.path.join(args.out_dir, "model.npz")
    config_path = os.path.join(args.out_dir, "config.json")
    tokenizer_path = os.path.join(args.out_dir, "tokenizer.json")
    history_path = os.path.join(args.out_dir, "history.json")

    config = {
        "vocab_size": tok.vocab_size,
        "n_embd": args.n_embd,
        "n_head": args.n_head,
        "n_layer": args.n_layer,
        "block_size": args.block_size,
    }
    save_checkpoint(model, config, weights_path, config_path)
    tok.save(tokenizer_path)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"saved checkpoint to {args.out_dir}/")
    return model, tok, history


def main():
    args = build_argparser().parse_args()
    train(args)


if __name__ == "__main__":
    main()
