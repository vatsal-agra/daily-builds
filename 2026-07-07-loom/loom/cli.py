"""`loom` command-line entry point."""
import argparse
import sys

import numpy as np

from .generate import generate
from .tokenizer import BPETokenizer
from .train import load_checkpoint, train


def cmd_tokenizer_train(args):
    text = open(args.corpus, encoding="utf-8").read()
    tok = BPETokenizer()
    tok.train(text, vocab_size=args.vocab_size, verbose=True)
    tok.save(args.out)
    print(f"trained tokenizer: {tok.vocab_size} tokens -> {args.out}")


def cmd_tokenizer_encode(args):
    tok = BPETokenizer.load(args.tokenizer)
    ids = tok.encode(args.text)
    print(" ".join(map(str, ids)))


def cmd_tokenizer_decode(args):
    tok = BPETokenizer.load(args.tokenizer)
    ids = [int(x) for x in args.ids.split()]
    print(tok.decode(ids))


def cmd_train(args):
    train(
        corpus_path=args.corpus,
        out_dir=args.out,
        vocab_size=args.vocab_size,
        n_embd=args.n_embd,
        n_head=args.n_head,
        n_layer=args.n_layer,
        block_size=args.block_size,
        batch_size=args.batch_size,
        steps=args.steps,
        lr=args.lr,
        seed=args.seed,
    )


def cmd_generate(args):
    model, tok, config = load_checkpoint(args.checkpoint)
    text = generate(
        model, tok, args.prompt, max_new_tokens=args.max_new_tokens,
        temperature=args.temperature, top_k=args.top_k, top_p=args.top_p,
        greedy=args.greedy, seed=args.seed,
    )
    print(text)


def cmd_chat(args):
    model, tok, config = load_checkpoint(args.checkpoint)
    print("Loom completion REPL. Type a prompt and press enter (Ctrl-D to quit).")
    while True:
        try:
            prompt = input("\n>>> ")
        except EOFError:
            print()
            break
        if not prompt.strip():
            continue
        text = generate(model, tok, prompt, max_new_tokens=args.max_new_tokens,
                         temperature=args.temperature, top_k=args.top_k, top_p=args.top_p)
        print(text)


def cmd_viz(args):
    from .viz import render_visualizer
    render_visualizer(args.checkpoint, args.out, prompt=args.prompt)
    print(f"wrote visualizer to {args.out}")


def build_parser():
    p = argparse.ArgumentParser(prog="loom", description="A tiny LLM built from scratch.")
    sub = p.add_subparsers(dest="command", required=True)

    tk = sub.add_parser("tokenizer", help="train/encode/decode with the BPE tokenizer")
    tksub = tk.add_subparsers(dest="tokenizer_command", required=True)

    tkt = tksub.add_parser("train")
    tkt.add_argument("--corpus", required=True)
    tkt.add_argument("--vocab-size", type=int, default=512)
    tkt.add_argument("--out", default="tokenizer.json")
    tkt.set_defaults(func=cmd_tokenizer_train)

    tke = tksub.add_parser("encode")
    tke.add_argument("--tokenizer", required=True)
    tke.add_argument("text")
    tke.set_defaults(func=cmd_tokenizer_encode)

    tkd = tksub.add_parser("decode")
    tkd.add_argument("--tokenizer", required=True)
    tkd.add_argument("ids")
    tkd.set_defaults(func=cmd_tokenizer_decode)

    tr = sub.add_parser("train", help="train a Loom model on a text corpus")
    tr.add_argument("--corpus", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--vocab-size", type=int, default=512)
    tr.add_argument("--n-embd", type=int, default=128)
    tr.add_argument("--n-head", type=int, default=4)
    tr.add_argument("--n-layer", type=int, default=4)
    tr.add_argument("--block-size", type=int, default=128)
    tr.add_argument("--batch-size", type=int, default=32)
    tr.add_argument("--steps", type=int, default=2000)
    tr.add_argument("--lr", type=float, default=3e-4)
    tr.add_argument("--seed", type=int, default=0)
    tr.set_defaults(func=cmd_train)

    gen = sub.add_parser("generate", help="complete a prompt with a trained checkpoint")
    gen.add_argument("--checkpoint", required=True)
    gen.add_argument("--prompt", default="")
    gen.add_argument("--max-new-tokens", type=int, default=200)
    gen.add_argument("--temperature", type=float, default=0.8)
    gen.add_argument("--top-k", type=int, default=None)
    gen.add_argument("--top-p", type=float, default=None)
    gen.add_argument("--greedy", action="store_true")
    gen.add_argument("--seed", type=int, default=None)
    gen.set_defaults(func=cmd_generate)

    chat = sub.add_parser("chat", help="interactive completion REPL")
    chat.add_argument("--checkpoint", required=True)
    chat.add_argument("--max-new-tokens", type=int, default=200)
    chat.add_argument("--temperature", type=float, default=0.8)
    chat.add_argument("--top-k", type=int, default=40)
    chat.add_argument("--top-p", type=float, default=None)
    chat.set_defaults(func=cmd_chat)

    viz = sub.add_parser("viz", help="render the interactive HTML visualizer")
    viz.add_argument("--checkpoint", required=True)
    viz.add_argument("--out", default="loom_viz.html")
    viz.add_argument("--prompt", default="ROMEO:")
    viz.set_defaults(func=cmd_viz)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
