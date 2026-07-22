#!/usr/bin/env python3
"""Prompt a trained Loom checkpoint and print a sampled continuation.

Example:
    python3 sample.py --checkpoint checkpoints/loom --prompt "The weaver" \
        --tokens 200 --temperature 0.8 --top-k 40
"""

import argparse
import sys

import numpy as np

from loom.checkpoint import load_checkpoint
from loom.generate import generate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", default="checkpoints/loom")
    ap.add_argument("--prompt", default="\n")
    ap.add_argument("--tokens", type=int, default=200)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--top-p", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-cache", action="store_true", help="disable KV-cache (slower, for comparison)")
    args = ap.parse_args()

    try:
        model, tokenizer, config, extra = load_checkpoint(args.checkpoint)
    except FileNotFoundError:
        print(f"error: no checkpoint found at '{args.checkpoint}.npz'/'.json' -- "
              f"run `python3 train.py --out {args.checkpoint}` first", file=sys.stderr)
        sys.exit(1)
    rng = np.random.default_rng(args.seed)

    text, ids = generate(
        model, tokenizer, args.prompt, args.tokens,
        temperature=args.temperature, top_k=args.top_k, top_p=args.top_p,
        rng=rng, use_cache=not args.no_cache,
    )
    print(text)


if __name__ == "__main__":
    main()
