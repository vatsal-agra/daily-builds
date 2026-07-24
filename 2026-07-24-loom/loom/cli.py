"""Unified `loom` CLI: train / generate / serve / attention subcommands."""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CKPT = os.path.join(HERE, "checkpoints", "loom-shakespeare")


def _load_checkpoint_or_die(path):
    from .checkpoint import load
    if not os.path.exists(os.path.join(path, "weights.npz")):
        print(f"error: no checkpoint found at {path!r} (missing weights.npz).", file=sys.stderr)
        print(f"  train one first: loom train --out {path}", file=sys.stderr)
        sys.exit(1)
    return load(path)


def cmd_generate(args):
    model, tokenizer, meta = _load_checkpoint_or_die(args.checkpoint)
    from .generate import generate_text
    text = generate_text(
        model, tokenizer, args.prompt,
        max_new_tokens=args.max_new_tokens, temperature=args.temperature,
        top_k=args.top_k, top_p=args.top_p, seed=args.seed,
    )
    print(text)


def cmd_serve(args):
    from . import server
    sys.argv = ["loom-server", "--checkpoint", args.checkpoint, "--port", str(args.port), "--host", args.host]
    server.main()


def cmd_attention(args):
    from .generate import attention_weights
    model, tokenizer, meta = _load_checkpoint_or_die(args.checkpoint)
    ids = tokenizer.encode(args.prompt)[:model.cfg.block_size]
    if not ids:
        print("prompt encoded to zero tokens", file=sys.stderr)
        sys.exit(1)
    tokens = [tokenizer.decode([i]) for i in ids]
    layers = attention_weights(model, ids)
    print(f"{len(layers)} layers x {layers[0].shape[0]} heads x {len(ids)} tokens")
    print("tokens:", tokens)
    print(f"(use `loom serve` for the interactive heatmap viewer)")


def main():
    # `train` is handled before argparse ever sees it: passing its many
    # flags through a subparser's nargs=REMAINDER positional is a known
    # argparse/subparsers footgun (flag-shaped tokens right after the
    # subcommand name get misparsed by the *outer* parser -- see the
    # REVIEW.md entry for the reproduction). Since loom.train has its own
    # complete argparse definition anyway, just hand off directly.
    argv = sys.argv[1:]
    if argv and argv[0] == "train":
        from . import train
        sys.argv = ["loom-train"] + argv[1:]
        train.main()
        return

    ap = argparse.ArgumentParser(prog="loom", description="Loom: a from-scratch tiny transformer LLM.")
    sub = ap.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate text from a trained checkpoint")
    g.add_argument("prompt", nargs="?", default="")
    g.add_argument("--checkpoint", default=DEFAULT_CKPT)
    g.add_argument("--max-new-tokens", type=int, default=200)
    g.add_argument("--temperature", type=float, default=0.8)
    g.add_argument("--top-k", type=int, default=40)
    g.add_argument("--top-p", type=float, default=0.0)
    g.add_argument("--seed", type=int, default=None)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("serve", help="serve the web UI + API for a trained checkpoint")
    s.add_argument("--checkpoint", default=DEFAULT_CKPT)
    s.add_argument("--port", type=int, default=8420)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(func=cmd_serve)

    a = sub.add_parser("attention", help="print attention-matrix shapes for a prompt (CLI sanity check)")
    a.add_argument("prompt")
    a.add_argument("--checkpoint", default=DEFAULT_CKPT)
    a.set_defaults(func=cmd_attention)

    sub.add_parser("train", help="train a model (see: loom train --help, handled before argparse above)")

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
