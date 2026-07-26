"""Autoregressive sampling from a trained Sprout model, plus a CLI.

Supports temperature scaling, top-k filtering, and top-p (nucleus) filtering,
composed in the standard order: temperature -> top-k -> top-p -> sample.
"""
import argparse
import sys

import numpy as np

from nn import softmax


def filter_logits(logits, top_k=None, top_p=None):
    logits = logits.copy()
    vocab_size = logits.shape[-1]

    if top_k is not None and top_k > 0:
        k = min(top_k, vocab_size)
        kth_val = np.partition(logits, -k)[-k]
        logits[logits < kth_val] = -np.inf

    if top_p is not None and 0.0 < top_p < 1.0:
        sorted_idx = np.argsort(-logits)
        sorted_logits = logits[sorted_idx]
        finite = np.isfinite(sorted_logits)
        sorted_probs = np.zeros_like(sorted_logits)
        sorted_probs[finite] = softmax(sorted_logits[finite])
        cum = np.cumsum(sorted_probs)
        cutoff = int(np.searchsorted(cum, top_p) + 1)
        cutoff = max(cutoff, 1)
        keep_mask = np.zeros(vocab_size, dtype=bool)
        keep_mask[sorted_idx[:cutoff]] = True
        logits = np.where(keep_mask, logits, -np.inf)

    return logits


def sample(model, tokenizer, prompt="", max_new_tokens=100, temperature=1.0, top_k=None, top_p=None, rng=None):
    """Returns the full generated text (prompt included)."""
    if rng is None:
        rng = np.random.default_rng()

    seed_prompt = prompt if prompt else " "
    ids = tokenizer.encode(seed_prompt)
    if not ids:
        ids = [ord(" ")]  # guaranteed valid byte-level token id (space)

    for _ in range(max_new_tokens):
        context = np.array([ids[-model.block_size :]])
        logits = model.forward(context)
        last_logits = logits[0, -1, :].astype(np.float64)

        if temperature <= 1e-6:
            next_id = int(np.argmax(last_logits))
        else:
            scaled = last_logits / temperature
            filtered = filter_logits(scaled, top_k=top_k, top_p=top_p)
            probs = softmax(filtered)
            probs = probs / probs.sum()  # renormalize after -inf filtering
            next_id = int(rng.choice(len(probs), p=probs))

        ids.append(next_id)

    return tokenizer.decode(ids)


def main():
    ap = argparse.ArgumentParser(description="Generate text from a trained Sprout checkpoint.")
    ap.add_argument("--checkpoint", default="checkpoints/sprout.pkl")
    ap.add_argument("--prompt", default=None, help="if omitted, enters interactive chat mode")
    ap.add_argument("--max-new-tokens", type=int, default=200)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=40)
    ap.add_argument("--top-p", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    from train import load_checkpoint  # local import: avoids a train<->generate import cycle

    try:
        model, tok, data = load_checkpoint(args.checkpoint)
    except FileNotFoundError:
        print(f"No checkpoint found at {args.checkpoint}. Run train.py first.", file=sys.stderr)
        raise SystemExit(1)

    rng = np.random.default_rng(args.seed)
    print(f"loaded checkpoint: step={data['step']}, {model.num_params():,} params, vocab={tok.vocab_size}")

    if args.prompt is not None:
        out = sample(
            model, tok, prompt=args.prompt, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, rng=rng,
        )
        print(out)
        return

    print("Interactive mode. Type a prompt and press enter (Ctrl-D to quit).")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            break
        if not prompt.strip():
            continue
        out = sample(
            model, tok, prompt=prompt, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, rng=rng,
        )
        print(out)


if __name__ == "__main__":
    main()
