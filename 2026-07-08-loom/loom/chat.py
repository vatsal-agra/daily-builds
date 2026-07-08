"""Interactive REPL: loads a checkpoint and streams generated tokens live."""
import argparse
import codecs
import os
import sys

import numpy as np

from .generate import load_generator
from .tensor import no_grad


def stream_generate(model, tok, prompt, max_new_tokens=200, temperature=0.8, top_k=40, rng=None):
    """Yields decoded text pieces as tokens are generated one at a time.

    A single BPE token's raw bytes are not guaranteed to be a complete UTF-8
    character on their own (a multi-byte character can be split across two
    adjacent tokens) -- naively decode-per-token would occasionally emit a
    U+FFFD replacement mid-word. We feed each token's raw bytes through a
    stdlib incremental UTF-8 decoder, which correctly buffers an incomplete
    trailing byte sequence until the rest arrives, and only ever falls back
    to replacement for bytes that are genuinely invalid.
    """
    rng = rng or np.random.default_rng()
    prompt_ids = tok.encode(prompt)
    if not prompt_ids:
        prompt_ids = [0]
    idx = np.array([prompt_ids], dtype=np.int64)
    max_new_tokens = max(0, min(max_new_tokens, model.block_size - idx.shape[1]))
    if max_new_tokens == 0:
        return

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def sample_next(logits_data):
        last = logits_data[:, -1, :] / max(temperature, 1e-8)
        if top_k is not None:
            k = min(top_k, last.shape[-1])
            kth = np.partition(last, -k, axis=-1)[:, -k:].min(axis=-1, keepdims=True)
            last = np.where(last < kth, -np.inf, last)
        m = last.max(axis=-1, keepdims=True)
        probs = np.exp(last - m)
        probs /= probs.sum(axis=-1, keepdims=True)
        return int(rng.choice(probs.shape[-1], p=probs[0]))

    with no_grad():
        kv_caches = model.new_kv_caches()
        logits, _ = model(idx, kv_caches=kv_caches)
        for _ in range(max_new_tokens):
            next_tok = sample_next(logits.data)
            piece = decoder.decode(tok.vocab[next_tok])
            if piece:
                yield piece
            logits, _ = model(np.array([[next_tok]]), kv_caches=kv_caches)
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def build_argparser():
    p = argparse.ArgumentParser(description="Interactive chat REPL over a trained Loom checkpoint.")
    p.add_argument("--checkpoint-dir", default=os.path.join(os.path.dirname(__file__), "..", "checkpoints"))
    p.add_argument("--max-new-tokens", type=int, default=200)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--top-k", type=int, default=40)
    p.add_argument("--seed", type=int, default=None)
    return p


def main(argv=None):
    ns = build_argparser().parse_args(argv)
    model, tok, config = load_generator(ns.checkpoint_dir)
    print(
        f"Loom chat -- {model.num_params():,} params, vocab_size={config['vocab_size']}, "
        f"block_size={config['block_size']}. Type a prompt; Ctrl-D or 'exit' to quit."
    )
    rng = np.random.default_rng(ns.seed)
    while True:
        try:
            prompt = input("\n> ")
        except EOFError:
            print()
            break
        if prompt.strip().lower() in ("exit", "quit"):
            break
        for piece in stream_generate(
            model, tok, prompt, ns.max_new_tokens, ns.temperature, ns.top_k, rng
        ):
            print(piece, end="", flush=True)
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
