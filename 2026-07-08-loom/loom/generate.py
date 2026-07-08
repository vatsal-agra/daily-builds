"""Autoregressive text generation from a trained checkpoint."""
import argparse
import os

import numpy as np

from .checkpoint import load_checkpoint
from .tokenizer import BPETokenizer


def load_generator(checkpoint_dir):
    weights_path = os.path.join(checkpoint_dir, "model.npz")
    config_path = os.path.join(checkpoint_dir, "config.json")
    tokenizer_path = os.path.join(checkpoint_dir, "tokenizer.json")
    model, config = load_checkpoint(weights_path, config_path)
    tok = BPETokenizer()
    tok.load(tokenizer_path)
    return model, tok, config


def generate_text(model, tok, prompt, max_new_tokens=200, temperature=0.8, top_k=40,
                   seed=None, use_kv_cache=True):
    rng = np.random.default_rng(seed)
    if prompt == "":
        prompt = " "  # need at least one token to seed generation; encode()
        # of any non-empty string always yields >=1 token (the pretokenizer
        # regex partitions every character into word/whitespace/other), so
        # no further empty-token-list fallback is needed after this point.
    prompt_ids = np.array([tok.encode(prompt)], dtype=np.int64)
    out_ids = model.generate(
        prompt_ids,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
        rng=rng,
        use_kv_cache=use_kv_cache,
    )
    return tok.decode(out_ids[0].tolist())


def build_argparser():
    p = argparse.ArgumentParser(description="Generate text from a trained Loom checkpoint.")
    p.add_argument("--checkpoint-dir", default=os.path.join(os.path.dirname(__file__), "..", "checkpoints"))
    p.add_argument("--prompt", default="Long ago, in the Whispering Forest,")
    p.add_argument("--max-new-tokens", type=int, default=200)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--top-k", type=int, default=40)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-kv-cache", action="store_true")
    return p


def main():
    args = build_argparser().parse_args()
    model, tok, config = load_generator(args.checkpoint_dir)
    text = generate_text(
        model, tok, args.prompt,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        seed=args.seed,
        use_kv_cache=not args.no_kv_cache,
    )
    print(text)


if __name__ == "__main__":
    main()
