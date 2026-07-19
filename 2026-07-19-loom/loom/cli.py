import argparse
import json
import os
import sys

import numpy as np

from .gradcheck import run_all as run_gradcheck
from .train import train as run_train
from .checkpoint import load_checkpoint
from .generate import generate


DEFAULT_CKPT = os.path.join(os.path.dirname(__file__), "..", "checkpoints", "loom")
DEFAULT_CORPUS = os.path.join(os.path.dirname(__file__), "..", "corpus", "loom_corpus.txt")


def cmd_gradcheck(args):
    results = run_gradcheck(verbose=True)
    n_ok = sum(results.values())
    print(f"\n{n_ok}/{len(results)} ops passed gradient check")
    sys.exit(0 if n_ok == len(results) else 1)


def cmd_train(args):
    out_path = args.out
    *_, best_val_loss = run_train(
        corpus_path=args.corpus,
        out_path=out_path,
        d_model=args.d_model,
        n_heads=args.n_heads,
        n_layers=args.n_layers,
        d_ff=args.d_ff,
        block_size=args.block_size,
        batch_size=args.batch_size,
        steps=args.steps,
        lr=args.lr,
        seed=args.seed,
        tokenizer_kind=args.tokenizer,
        bpe_merges=args.bpe_merges,
    )
    print(f"\nSaved best-validation checkpoint (val_loss={best_val_loss:.4f}) to {out_path}(.npz/.json)")


def cmd_generate(args):
    model, tokenizer, config = load_checkpoint(args.ckpt)
    text = generate(
        model, tokenizer, args.prompt,
        max_new_tokens=args.n,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        seed=args.seed,
    )
    print(text)


ATTN_FRAME_WARN_THRESHOLD = 150


def cmd_attn(args):
    from .attn_viz import render as render_viz
    model, tokenizer, config = load_checkpoint(args.ckpt)
    if args.n > ATTN_FRAME_WARN_THRESHOLD:
        print(
            f"warning: -n {args.n} captures one attention frame per generated token; "
            f"each frame embeds every layer/head's full context-length x context-length "
            f"matrix as JSON, so large -n can produce a very large, slow-to-load HTML file. "
            f"Consider -n <= {ATTN_FRAME_WARN_THRESHOLD} for the visualizer.",
            file=sys.stderr,
        )
    text, frames = generate(
        model, tokenizer, args.prompt,
        max_new_tokens=args.n,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        seed=args.seed,
        return_attn=True,
    )
    if args.out.endswith(".html"):
        render_viz(frames, text, args.out)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"text": text, "frames": frames}, f)
    print(f"Wrote {len(frames)} attention frames to {args.out}")
    print(text)


def cmd_tokenize(args):
    from .tokenizer import CharTokenizer
    with open(args.corpus, "r", encoding="utf-8") as f:
        text = f.read()
    tok = CharTokenizer(text)
    ids = tok.encode(text[:200])
    decoded = tok.decode(ids)
    assert decoded == text[:200], "char tokenizer round-trip failed"
    print(f"vocab_size={tok.vocab_size}")
    print(f"round-trip OK on first 200 chars")


def cmd_bpe(args):
    from .tokenizer import BPETokenizer
    with open(args.corpus, "r", encoding="utf-8") as f:
        text = f.read()
    tok = BPETokenizer()
    train_ids = tok.train(text, num_merges=args.merges)
    print(f"trained {len(tok.merges)} merges -> vocab_size={tok.vocab_size}")
    print(f"corpus: {len(text)} chars -> {len(text.encode('utf-8'))} raw bytes -> {len(train_ids)} BPE tokens "
          f"({len(text.encode('utf-8')) / max(1, len(train_ids)):.2f}x compression)")
    sample = text[:300]
    ids = tok.encode(sample)
    decoded = tok.decode(ids)
    assert decoded == sample, "BPE round-trip failed"
    print(f"round-trip OK on first 300 chars ({len(ids)} tokens)")
    top_merges = list(tok.merges.items())[:8]
    for (a, b), new_id in top_merges:
        print(f"  merge {new_id}: {tok.vocab[a]!r} + {tok.vocab[b]!r} -> {tok.vocab[new_id]!r}")


def build_parser():
    p = argparse.ArgumentParser(prog="loom", description="A from-scratch transformer LM.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gradcheck", help="verify every autodiff op against numerical gradients")
    g.set_defaults(func=cmd_gradcheck)

    t = sub.add_parser("train", help="train a GPT-style model on a corpus")
    t.add_argument("--corpus", default=DEFAULT_CORPUS)
    t.add_argument("--out", default=DEFAULT_CKPT)
    t.add_argument("--d-model", dest="d_model", type=int, default=64)
    t.add_argument("--n-heads", dest="n_heads", type=int, default=4)
    t.add_argument("--n-layers", dest="n_layers", type=int, default=3)
    t.add_argument("--d-ff", dest="d_ff", type=int, default=256)
    t.add_argument("--block-size", dest="block_size", type=int, default=64)
    t.add_argument("--batch-size", dest="batch_size", type=int, default=32)
    t.add_argument("--steps", type=int, default=2000)
    t.add_argument("--lr", type=float, default=3e-3)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--tokenizer", choices=["char", "bpe"], default="char")
    t.add_argument("--bpe-merges", dest="bpe_merges", type=int, default=200)
    t.set_defaults(func=cmd_train)

    gen = sub.add_parser("generate", help="sample text from a trained checkpoint")
    gen.add_argument("--ckpt", default=DEFAULT_CKPT)
    gen.add_argument("--prompt", default="The ")
    gen.add_argument("-n", type=int, default=300)
    gen.add_argument("--temperature", type=float, default=0.8)
    gen.add_argument("--top-k", dest="top_k", type=int, default=None)
    gen.add_argument("--top-p", dest="top_p", type=float, default=None)
    gen.add_argument("--seed", type=int, default=None)
    gen.set_defaults(func=cmd_generate)

    a = sub.add_parser("attn", help="generate and dump attention-weight frames for the visualizer")
    a.add_argument("--ckpt", default=DEFAULT_CKPT)
    a.add_argument("--prompt", default="The ")
    a.add_argument("-n", type=int, default=40)
    a.add_argument("--temperature", type=float, default=0.8)
    a.add_argument("--top-k", dest="top_k", type=int, default=None)
    a.add_argument("--top-p", dest="top_p", type=float, default=None)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--out", default="viz/attention.html",
                   help="path to write; .html renders the interactive visualizer, anything else dumps raw JSON frames")
    a.set_defaults(func=cmd_attn)

    tok = sub.add_parser("tokenize", help="sanity-check the char tokenizer round-trip")
    tok.add_argument("--corpus", default=DEFAULT_CORPUS)
    tok.set_defaults(func=cmd_tokenize)

    bpe = sub.add_parser("bpe", help="train a from-scratch BPE tokenizer on a corpus and show its merges")
    bpe.add_argument("--corpus", default=DEFAULT_CORPUS)
    bpe.add_argument("--merges", type=int, default=200)
    bpe.set_defaults(func=cmd_bpe)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
