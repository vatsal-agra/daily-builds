#!/usr/bin/env python3
"""Loom CLI: tokenizer-train, gradcheck, train, sample, viz, demo."""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loom.gradcheck import gradcheck_model
from loom.model import TransformerLM
from loom.sample import generate
from loom.tokenizer import BPETokenizer
from loom.train import load_checkpoint, train
from loom import viz as viz_mod

DEFAULT_CORPUS = os.path.join(os.path.dirname(__file__), "loom", "data", "corpus.txt")
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "runs", "default")


def cmd_tokenizer_train(args):
    with open(args.corpus, encoding="utf-8") as f:
        text = f.read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=args.vocab_size, verbose=True)
    tok.save(args.out)
    ids = tok.encode(text[:2000])
    roundtrip = tok.decode(ids) == text[:2000]
    print(f"trained vocab_size={tok.vocab_size}, saved to {args.out}")
    print(f"round-trip check on first 2000 chars: {'OK' if roundtrip else 'FAILED'}")
    if not roundtrip:
        sys.exit(1)


def cmd_gradcheck(args):
    rng = np.random.RandomState(args.seed)
    model = TransformerLM(
        vocab_size=args.vocab_size, d_model=args.d_model, n_heads=args.n_heads,
        n_layers=args.n_layers, max_seq_len=args.seq_len, seed=args.seed,
    )
    ids = rng.randint(0, args.vocab_size, size=(args.batch_size, args.seq_len))
    targets = rng.randint(0, args.vocab_size, size=(args.batch_size, args.seq_len))
    results = gradcheck_model(model, ids, targets, num_samples=args.samples, seed=args.seed)
    n_params = sum(np.prod(r["shape"]) for r in results)
    worst = max(results, key=lambda r: r["max_rel_diff"])
    print(f"gradcheck PASSED: {len(results)} parameter tensors ({int(n_params)} total scalars), "
          f"worst max_rel_diff={worst['max_rel_diff']:.2e} (param {worst['param_index']}, shape {worst['shape']})")


def cmd_train(args):
    model, tok, losses = train(
        corpus_path=args.corpus, out_dir=args.out, vocab_size=args.vocab_size,
        d_model=args.d_model, n_heads=args.n_heads, n_layers=args.n_layers,
        seq_len=args.seq_len, batch_size=args.batch_size, steps=args.steps,
        lr=args.lr, warmup_steps=args.warmup, weight_decay=args.weight_decay,
        seed=args.seed, log_every=args.log_every, ckpt_every=args.ckpt_every,
    )
    print(f"done. first loss={losses[0]:.4f} last loss={losses[-1]:.4f} "
          f"checkpoint dir={args.out}")


def cmd_sample(args):
    model = load_checkpoint(os.path.join(args.run, "model.npz"), os.path.join(args.run, "config.json"))
    tok = BPETokenizer.load(os.path.join(args.run, "tokenizer.json"))
    top_k = args.top_k if args.top_k > 0 else None
    top_p = args.top_p if args.top_p > 0 else None
    text, ids = generate(
        model, tok, args.prompt, max_new_tokens=args.max_new_tokens,
        temperature=args.temperature, top_k=top_k, top_p=top_p, seed=args.seed,
    )
    print(text)


def cmd_viz(args):
    model = load_checkpoint(os.path.join(args.run, "model.npz"), os.path.join(args.run, "config.json"))
    tok = BPETokenizer.load(os.path.join(args.run, "tokenizer.json"))
    log_path = os.path.join(args.run, "train_log.jsonl")
    out_path = viz_mod.render(args.prompt, model, tok, log_path=log_path, out_path=args.out)
    print(f"wrote {out_path}")


def cmd_demo(args):
    run_dir = os.path.join(os.path.dirname(__file__), "runs", "demo")
    print("== 1. train tokenizer + tiny model (fast settings) ==")
    train(
        corpus_path=DEFAULT_CORPUS, out_dir=run_dir, vocab_size=384, d_model=64,
        n_heads=4, n_layers=2, seq_len=64, batch_size=24, steps=300, lr=3e-3,
        warmup_steps=30, seed=0, log_every=50, ckpt_every=300,
    )
    print("\n== 2. gradcheck ==")
    class A: pass
    a = A(); a.vocab_size = 17; a.d_model = 8; a.n_heads = 2; a.n_layers = 2
    a.seq_len = 5; a.batch_size = 2; a.samples = 3; a.seed = 0
    cmd_gradcheck(a)

    print("\n== 3. sample from the trained checkpoint ==")
    class B: pass
    b = B(); b.run = run_dir; b.prompt = "ROMEO:"; b.max_new_tokens = 120
    b.temperature = 0.8; b.top_k = 40; b.top_p = 0.0; b.seed = 0
    cmd_sample(b)

    print("\n== 4. render visualizer ==")
    class C: pass
    c = C(); c.run = run_dir; c.prompt = "ROMEO: what light"; c.out = os.path.join(run_dir, "viz.html")
    cmd_viz(c)
    print("\ndemo complete.")


def build_parser():
    p = argparse.ArgumentParser(description="Loom: a from-scratch transformer language model")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tokenizer-train", help="train a BPE tokenizer on a corpus")
    t.add_argument("--corpus", default=DEFAULT_CORPUS)
    t.add_argument("--vocab-size", type=int, default=512)
    t.add_argument("--out", default=os.path.join(DEFAULT_OUT, "tokenizer.json"))
    t.set_defaults(func=cmd_tokenizer_train)

    g = sub.add_parser("gradcheck", help="finite-difference gradient check of the whole model")
    g.add_argument("--vocab-size", type=int, default=17)
    g.add_argument("--d-model", type=int, default=8)
    g.add_argument("--n-heads", type=int, default=2)
    g.add_argument("--n-layers", type=int, default=2)
    g.add_argument("--seq-len", type=int, default=5)
    g.add_argument("--batch-size", type=int, default=2)
    g.add_argument("--samples", type=int, default=4)
    g.add_argument("--seed", type=int, default=0)
    g.set_defaults(func=cmd_gradcheck)

    tr = sub.add_parser("train", help="train a Loom model on a text corpus")
    tr.add_argument("--corpus", default=DEFAULT_CORPUS)
    tr.add_argument("--out", default=DEFAULT_OUT)
    tr.add_argument("--vocab-size", type=int, default=512)
    tr.add_argument("--d-model", type=int, default=128)
    tr.add_argument("--n-heads", type=int, default=4)
    tr.add_argument("--n-layers", type=int, default=4)
    tr.add_argument("--seq-len", type=int, default=128)
    tr.add_argument("--batch-size", type=int, default=32)
    tr.add_argument("--steps", type=int, default=2000)
    tr.add_argument("--lr", type=float, default=3e-4)
    tr.add_argument("--warmup", type=int, default=100)
    tr.add_argument("--weight-decay", type=float, default=0.01)
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--log-every", type=int, default=20)
    tr.add_argument("--ckpt-every", type=int, default=500)
    tr.set_defaults(func=cmd_train)

    s = sub.add_parser("sample", help="generate text from a trained checkpoint")
    s.add_argument("--run", default=DEFAULT_OUT)
    s.add_argument("--prompt", default="")
    s.add_argument("--max-new-tokens", type=int, default=200)
    s.add_argument("--temperature", type=float, default=0.8)
    s.add_argument("--top-k", type=int, default=0, help="0 disables top-k")
    s.add_argument("--top-p", type=float, default=0.0, help="0 disables top-p")
    s.add_argument("--seed", type=int, default=None)
    s.set_defaults(func=cmd_sample)

    v = sub.add_parser("viz", help="render the attention/loss HTML visualizer")
    v.add_argument("--run", default=DEFAULT_OUT)
    v.add_argument("--prompt", default="ROMEO:")
    v.add_argument("--out", default=os.path.join(DEFAULT_OUT, "viz.html"))
    v.set_defaults(func=cmd_viz)

    d = sub.add_parser("demo", help="run the full pipeline end-to-end on fast settings")
    d.set_defaults(func=cmd_demo)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
