"""Unified CLI: `python3 -m loom.cli <command> ...`"""
import argparse
import json
import sys
import time

import numpy as np

from . import train as train_mod
from .export_trace import export_trace
from .generate import generate_cached, generate_naive, generate_text


def cmd_train(args):
    train_mod.train(
        corpus_path=args.corpus, ckpt_dir=args.ckpt_dir, vocab_size=args.vocab_size,
        n_ctx=args.n_ctx, n_embd=args.n_embd, n_head=args.n_head, n_layer=args.n_layer,
        batch_size=args.batch_size, steps=args.steps, lr=args.lr, seed=args.seed,
        log_path=args.log_path,
    )


def cmd_generate(args):
    model, tokenizer, config, step = train_mod.load_checkpoint(args.ckpt_dir)
    text = generate_text(
        model, tokenizer, args.prompt, config.n_ctx, max_new_tokens=args.max_new_tokens,
        temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, seed=args.seed,
        use_cache=args.use_cache,
    )
    print(text)


def cmd_bench(args):
    model, tokenizer, config, step = train_mod.load_checkpoint(args.ckpt_dir)
    rng = np.random.default_rng(args.seed)
    prompt_ids = tokenizer.encode(args.prompt) if args.prompt else [0]
    idx = np.array([prompt_ids], dtype=np.int64)
    n = min(args.max_new_tokens, config.n_ctx - len(prompt_ids))

    t0 = time.time()
    out_naive = generate_naive(model, idx, n, config.n_ctx, temperature=1e-6,
                                top_k=1, rng=np.random.default_rng(args.seed))
    t_naive = time.time() - t0

    t0 = time.time()
    out_cached = generate_cached(model, idx, n, config.n_ctx, temperature=1e-6,
                                  top_k=1, rng=np.random.default_rng(args.seed))
    t_cached = time.time() - t0

    parity = bool(np.array_equal(out_naive, out_cached))
    print(json.dumps({
        "new_tokens": n, "naive_seconds": t_naive, "cached_seconds": t_cached,
        "speedup": t_naive / t_cached if t_cached > 0 else None, "identical_output": parity,
    }, indent=2))


def cmd_viz(args):
    model, tokenizer, config, step = train_mod.load_checkpoint(args.ckpt_dir)
    trace = export_trace(model, tokenizer, config, args.text, args.out,
                          max_gen_steps=args.max_gen_steps, seed=args.seed)
    print(f"wrote trace to {args.out} ({len(trace['tokens'])} input tokens, "
          f"{len(trace['generation'])} generation steps)")


def build_parser():
    p = argparse.ArgumentParser(prog="loom")
    sub = p.add_subparsers(dest="command", required=True)

    pt = sub.add_parser("train")
    pt.add_argument("--corpus", default="corpus/fables.txt")
    pt.add_argument("--ckpt-dir", default="checkpoints/loom-small")
    pt.add_argument("--vocab-size", type=int, default=384)
    pt.add_argument("--n-ctx", type=int, default=64)
    pt.add_argument("--n-embd", type=int, default=96)
    pt.add_argument("--n-head", type=int, default=4)
    pt.add_argument("--n-layer", type=int, default=3)
    pt.add_argument("--batch-size", type=int, default=24)
    pt.add_argument("--steps", type=int, default=2500)
    pt.add_argument("--lr", type=float, default=3e-3)
    pt.add_argument("--seed", type=int, default=0)
    pt.add_argument("--log-path", default=None)
    pt.set_defaults(func=cmd_train)

    pg = sub.add_parser("generate")
    pg.add_argument("--ckpt-dir", default="checkpoints/loom-small")
    pg.add_argument("--prompt", default="")
    pg.add_argument("--max-new-tokens", type=int, default=150)
    pg.add_argument("--temperature", type=float, default=0.9)
    pg.add_argument("--top-k", type=int, default=40)
    pg.add_argument("--top-p", type=float, default=0.95)
    pg.add_argument("--seed", type=int, default=0)
    pg.add_argument("--use-cache", action="store_true")
    pg.set_defaults(func=cmd_generate)

    pb = sub.add_parser("bench")
    pb.add_argument("--ckpt-dir", default="checkpoints/loom-small")
    pb.add_argument("--prompt", default="Long before")
    pb.add_argument("--max-new-tokens", type=int, default=60)
    pb.add_argument("--seed", type=int, default=0)
    pb.set_defaults(func=cmd_bench)

    pv = sub.add_parser("viz")
    pv.add_argument("--ckpt-dir", default="checkpoints/loom-small")
    pv.add_argument("--text", default="The clever fox wanted")
    pv.add_argument("--out", default="viz/trace.json")
    pv.add_argument("--max-gen-steps", type=int, default=30)
    pv.add_argument("--seed", type=int, default=0)
    pv.set_defaults(func=cmd_viz)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
