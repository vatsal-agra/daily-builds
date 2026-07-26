#!/usr/bin/env python3
"""Loom CLI: train / generate / chat / tokenize / gradcheck / viz / demo."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_train(args):
    from loom.train import build_argparser, train

    train_args = build_argparser().parse_args(args)
    train(train_args)


def cmd_generate(args):
    from loom.generate import build_argparser, load_generator, generate_text

    p = build_argparser()
    ns = p.parse_args(args)
    model, tok, config = load_generator(ns.checkpoint_dir)
    text = generate_text(
        model, tok, ns.prompt,
        max_new_tokens=ns.max_new_tokens,
        temperature=ns.temperature,
        top_k=ns.top_k,
        seed=ns.seed,
        use_kv_cache=not ns.no_kv_cache,
    )
    print(text)


def cmd_chat(args):
    from loom.chat import main as chat_main

    chat_main(args)


def cmd_tokenize(args):
    p = argparse.ArgumentParser(prog="cli.py tokenize")
    p.add_argument("--corpus", required=True)
    p.add_argument("--vocab-size", type=int, default=512)
    p.add_argument("--out", required=True)
    p.add_argument("--text", help="if given, also print encode/decode of this text")
    ns = p.parse_args(args)

    from loom.tokenizer import BPETokenizer

    with open(ns.corpus) as f:
        corpus_text = f.read()
    tok = BPETokenizer()
    tok.train(corpus_text, vocab_size=ns.vocab_size, verbose=True)
    tok.save(ns.out)
    print(f"trained tokenizer: vocab_size={tok.vocab_size}, saved to {ns.out}")
    if ns.text is not None:
        ids = tok.encode(ns.text)
        print(f"encode({ns.text!r}) = {ids}")
        print(f"decode(...) = {tok.decode(ids)!r}")


def cmd_gradcheck(args):
    import unittest

    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(os.path.dirname(__file__), "tests"), pattern="test_tensor.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def cmd_viz(args):
    from loom.viz import build_argparser, main as viz_main

    viz_main(args)


def cmd_demo(args):
    import subprocess

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.sh")
    sys.exit(subprocess.call(["bash", script]))


COMMANDS = {
    "train": cmd_train,
    "generate": cmd_generate,
    "chat": cmd_chat,
    "tokenize": cmd_tokenize,
    "gradcheck": cmd_gradcheck,
    "viz": cmd_viz,
    "demo": cmd_demo,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: cli.py <{'|'.join(COMMANDS)}> [args...]")
        sys.exit(1)
    try:
        COMMANDS[sys.argv[1]](sys.argv[2:])
    except (FileNotFoundError, ValueError) as e:
        # user-facing input/config errors: print cleanly, no traceback noise
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
