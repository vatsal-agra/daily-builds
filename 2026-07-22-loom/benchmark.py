#!/usr/bin/env python3
"""Benchmark KV-cache generation against full-recompute generation.

Stretch feature #5 from PLAN.md: incremental decoding should be
substantially faster than recomputing attention over the whole sequence
from scratch at every step, because it avoids redundant O(T^2) work per
step (full recompute) in favor of O(T) work per step (cache).
"""

import argparse
import time

import numpy as np

from loom.checkpoint import load_checkpoint
from loom.generate import generate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", default="checkpoints/loom")
    ap.add_argument("--prompt", default="The weaver kept her loom")
    ap.add_argument("--tokens", type=int, default=40)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    model, tokenizer, config, extra = load_checkpoint(args.checkpoint)
    print(f"model: {model.num_params():,} params, {len(model.blocks)} layers, "
          f"context {model.max_seq_len}\n")

    def timed(use_cache):
        times = []
        for i in range(args.repeats):
            t0 = time.time()
            generate(model, tokenizer, args.prompt, args.tokens, temperature=0.8, top_k=40,
                     rng=np.random.default_rng(i), use_cache=use_cache)
            times.append(time.time() - t0)
        return times

    print(f"generating {args.tokens} tokens, {args.repeats} repeats each ...")
    cached_times = timed(True)
    full_times = timed(False)

    cached_mean = np.mean(cached_times)
    full_mean = np.mean(full_times)

    print(f"\n{'method':<20}{'mean sec':>12}{'sec/token':>14}")
    print(f"{'KV-cache':<20}{cached_mean:>12.4f}{cached_mean/args.tokens:>14.5f}")
    print(f"{'full recompute':<20}{full_mean:>12.4f}{full_mean/args.tokens:>14.5f}")
    print(f"\nspeedup: {full_mean / cached_mean:.2f}x")


if __name__ == "__main__":
    main()
