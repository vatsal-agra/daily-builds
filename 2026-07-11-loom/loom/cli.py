"""Command-line entry point: `loom train / generate / tokenize / gradcheck /
viz / demo`."""
import argparse
import json
import sys

import numpy as np


def cmd_train(args):
    from .train import train

    with open(args.corpus, encoding="utf-8") as f:
        text = f.read()
    train(
        text,
        out_dir=args.out,
        num_merges=args.merges,
        block_size=args.block_size,
        n_embd=args.n_embd,
        n_head=args.n_head,
        n_layer=args.n_layer,
        batch_size=args.batch_size,
        steps=args.steps,
        lr=args.lr,
        eval_every=args.eval_every,
        seed=args.seed,
    )
    print(f"checkpoint saved to {args.out}")


def cmd_generate(args):
    from . import checkpoint
    from .sample import generate

    model, tokenizer, meta = checkpoint.load(args.checkpoint)
    text, _ = generate(
        model, tokenizer, prompt=args.prompt, max_new_tokens=args.tokens,
        temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, seed=args.seed,
    )
    print(text)


def cmd_tokenize(args):
    from .tokenizer import ByteBPETokenizer

    with open(args.corpus, encoding="utf-8") as f:
        text = f.read()
    tok = ByteBPETokenizer()
    tok.train(text, num_merges=args.merges, verbose=args.verbose)
    if args.out:
        tok.save(args.out)
        print(f"tokenizer saved to {args.out} (vocab_size={tok.vocab_size})")
    else:
        print(f"vocab_size={tok.vocab_size}")
    sample = args.sample or text[:200]
    ids = tok.encode(sample)
    print(f"sample encode ({len(sample)} chars -> {len(ids)} tokens): {ids[:40]}{'...' if len(ids) > 40 else ''}")
    assert tok.decode(ids) == sample, "round-trip failed!"
    print("round-trip check: OK")


def cmd_gradcheck(args):
    from .nn import GPT
    from . import gradcheck

    rng = np.random.default_rng(args.seed)
    model = GPT(vocab_size=args.vocab_size, block_size=args.block_size, n_embd=args.n_embd,
                n_head=args.n_head, n_layer=args.n_layer, seed=args.seed)
    idx = rng.integers(0, args.vocab_size, size=(2, args.block_size))
    targets = rng.integers(0, args.vocab_size, size=(2, args.block_size))
    params = model.parameters()
    names = [f"param_{i}_{p.data.shape}" for i, p in enumerate(params)]

    def f():
        _, loss = model(idx, targets)
        return loss

    ok, report = gradcheck.check(f, params, names=names, eps=1e-5, tol=2e-3)
    print("\n".join(report))
    if not ok:
        print("GRADCHECK FAILED", file=sys.stderr)
        sys.exit(1)
    print(f"gradcheck OK across {len(params)} parameter tensors")


def cmd_viz(args):
    from . import checkpoint
    from .sample import generate
    from .viz import render_html

    model, tokenizer, meta = checkpoint.load(args.checkpoint)
    text, trace = generate(
        model, tokenizer, prompt=args.prompt, max_new_tokens=args.tokens,
        temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, seed=args.seed,
        capture_attn=True,
    )
    html = render_html(model, tokenizer, meta, trace, prompt=args.prompt)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out} ({len(html)} bytes); generated text preview: {text[:120]!r}")


def cmd_demo(args):
    from .demo import run_demo

    run_demo(seed=args.seed)


def build_parser():
    p = argparse.ArgumentParser(prog="loom", description="A Transformer LM built on a from-scratch tensor autodiff engine.")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("train", help="train a BPE tokenizer + GPT model on a text corpus")
    t.add_argument("corpus", help="path to a UTF-8 text file")
    t.add_argument("--out", default="checkpoint", help="output checkpoint directory")
    t.add_argument("--merges", type=int, default=300)
    t.add_argument("--block-size", type=int, default=64)
    t.add_argument("--n-embd", type=int, default=64)
    t.add_argument("--n-head", type=int, default=4)
    t.add_argument("--n-layer", type=int, default=2)
    t.add_argument("--batch-size", type=int, default=16)
    t.add_argument("--steps", type=int, default=300)
    t.add_argument("--lr", type=float, default=3e-3)
    t.add_argument("--eval-every", type=int, default=25)
    t.add_argument("--seed", type=int, default=0)
    t.set_defaults(func=cmd_train)

    g = sub.add_parser("generate", help="sample text from a trained checkpoint")
    g.add_argument("checkpoint")
    g.add_argument("--prompt", default="")
    g.add_argument("--tokens", type=int, default=200)
    g.add_argument("--temperature", type=float, default=0.8)
    g.add_argument("--top-k", type=int, default=None)
    g.add_argument("--top-p", type=float, default=None)
    g.add_argument("--seed", type=int, default=None)
    g.set_defaults(func=cmd_generate)

    tk = sub.add_parser("tokenize", help="train and inspect a BPE tokenizer")
    tk.add_argument("corpus")
    tk.add_argument("--merges", type=int, default=300)
    tk.add_argument("--out", default=None)
    tk.add_argument("--sample", default=None)
    tk.add_argument("--verbose", action="store_true")
    tk.set_defaults(func=cmd_tokenize)

    gc = sub.add_parser("gradcheck", help="finite-difference gradient check on a random tiny GPT")
    gc.add_argument("--vocab-size", type=int, default=13)
    gc.add_argument("--block-size", type=int, default=5)
    gc.add_argument("--n-embd", type=int, default=8)
    gc.add_argument("--n-head", type=int, default=2)
    gc.add_argument("--n-layer", type=int, default=2)
    gc.add_argument("--seed", type=int, default=0)
    gc.set_defaults(func=cmd_gradcheck)

    vz = sub.add_parser("viz", help="render an interactive HTML attention/generation visualizer")
    vz.add_argument("checkpoint")
    vz.add_argument("--prompt", default="The")
    vz.add_argument("--tokens", type=int, default=60)
    vz.add_argument("--temperature", type=float, default=0.8)
    vz.add_argument("--top-k", type=int, default=40)
    vz.add_argument("--top-p", type=float, default=None)
    vz.add_argument("--seed", type=int, default=0)
    vz.add_argument("--out", default="loom_viz.html")
    vz.set_defaults(func=cmd_viz)

    dm = sub.add_parser("demo", help="run the entire pipeline end to end on the bundled corpus")
    dm.add_argument("--seed", type=int, default=0)
    dm.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"loom: error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
