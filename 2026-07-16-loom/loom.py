#!/usr/bin/env python3
"""Loom CLI -- a tiny GPT-style language model, built from scratch.

Subcommands:
  train-tokenizer   train a byte-level BPE tokenizer on a corpus
  train             train a GPT model on tokenized corpus, save a checkpoint
  generate          sample text from a trained checkpoint
  chat              interactive REPL that keeps sampling from a checkpoint
  attn-viz          render an interactive attention-weights HTML page
  gradcheck         run the numerical-vs-analytic gradient check suite
  demo              run the whole pipeline end-to-end with small settings
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from loom.tokenizer import BPETokenizer
from loom.model import GPT
from loom.train import train as train_loop, save_checkpoint, load_checkpoint, min_tokens_required
from loom.generate import generate as sample_generate
from loom import gradcheck as gradcheck_mod


def _read_text_file(path: str, what: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"ERROR: {what} not found: {path}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: could not read {what} {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _load_tokenizer(path: str) -> BPETokenizer:
    try:
        return BPETokenizer.load(path)
    except FileNotFoundError:
        print(f"ERROR: tokenizer file not found: {path} "
              f"(run 'train-tokenizer' first)", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, IndexError) as e:
        print(f"ERROR: tokenizer file {path} is corrupt or invalid: {e}", file=sys.stderr)
        sys.exit(1)


def _load_model_checkpoint(path: str) -> GPT:
    try:
        return load_checkpoint(path)
    except FileNotFoundError:
        print(f"ERROR: checkpoint file not found: {path} (run 'train' first)", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, OSError) as e:
        print(f"ERROR: checkpoint file {path} is corrupt or invalid: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_train_tokenizer(args):
    text = _read_text_file(args.corpus, "corpus")
    tok = BPETokenizer()
    print(f"Training BPE tokenizer to vocab_size={args.vocab_size} on {len(text)} chars...")
    tok.train(text, args.vocab_size, verbose=args.verbose)
    tok.save(args.out)
    ids = tok.encode(text)
    roundtrip = tok.decode(ids)
    ok = roundtrip == text
    print(f"Learned {len(tok.merges)} merges -> vocab_size={tok.vocab_size}")
    print(f"Corpus encodes to {len(ids)} tokens ({len(text) / max(1, len(ids)):.2f} chars/token)")
    print(f"Round-trip exact: {ok}")
    if not ok:
        print("ERROR: tokenizer failed to round-trip the training corpus!", file=sys.stderr)
        sys.exit(1)
    print(f"Saved tokenizer to {args.out}")


def cmd_train(args):
    if args.steps < 1:
        print(f"ERROR: --steps must be >= 1 (got {args.steps})", file=sys.stderr)
        sys.exit(1)

    text = _read_text_file(args.corpus, "corpus")
    tok = _load_tokenizer(args.tokenizer)
    ids = np.array(tok.encode(text), dtype=np.int64)
    print(f"Corpus: {len(text)} chars -> {len(ids)} tokens (vocab_size={tok.vocab_size})")

    required = min_tokens_required(args.block_size)
    if len(ids) < required:
        print(f"ERROR: corpus has only {len(ids)} tokens, need at least {required} "
              f"for block_size={args.block_size}", file=sys.stderr)
        sys.exit(1)

    model = GPT(vocab_size=tok.vocab_size, d_model=args.d_model, n_layer=args.n_layer,
                n_head=args.n_head, block_size=args.block_size, seed=args.seed)
    print(f"Model: {model.num_params():,} parameters "
          f"(d_model={args.d_model}, n_layer={args.n_layer}, n_head={args.n_head}, "
          f"block_size={args.block_size})")

    def on_log(step, loss, lr, elapsed):
        print(f"  step {step:5d}/{args.steps}  loss={loss:.4f}  lr={lr:.2e}  "
              f"({elapsed:.1f}s elapsed)")

    t0 = time.time()
    history = train_loop(model, ids, steps=args.steps, batch_size=args.batch_size,
                          base_lr=args.lr, seed=args.seed, log_every=args.log_every,
                          on_log=on_log)
    print(f"Training done in {time.time() - t0:.1f}s. "
          f"Loss: {history[0][1]:.4f} -> {history[-1][1]:.4f}")
    save_checkpoint(args.out, model)
    if args.history_out:
        with open(args.history_out, "w") as f:
            for step, loss in history:
                f.write(f"{step},{loss}\n")
    print(f"Saved checkpoint to {args.out}")


def _load_for_inference(checkpoint_path, tokenizer_path):
    model = _load_model_checkpoint(checkpoint_path)
    tok = _load_tokenizer(tokenizer_path)
    if tok.vocab_size != model.vocab_size:
        print(f"ERROR: tokenizer vocab_size={tok.vocab_size} does not match "
              f"checkpoint vocab_size={model.vocab_size}", file=sys.stderr)
        sys.exit(1)
    return model, tok


def cmd_generate(args):
    model, tok = _load_for_inference(args.checkpoint, args.tokenizer)
    if not args.prompt.strip():
        print("ERROR: --prompt must be non-empty", file=sys.stderr)
        sys.exit(1)
    prompt_ids = tok.encode(args.prompt)
    rng = np.random.default_rng(args.seed)
    out_ids = sample_generate(model, prompt_ids, max_new_tokens=args.max_new_tokens,
                               temperature=args.temperature, top_k=args.top_k,
                               top_p=args.top_p, rng=rng)
    print(tok.decode(out_ids))


def cmd_chat(args):
    model, tok = _load_for_inference(args.checkpoint, args.tokenizer)
    print("Loom chat REPL. Type a prompt and press enter; Ctrl-D or 'quit' to exit.")
    rng = np.random.default_rng(args.seed)
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            break
        if prompt.strip().lower() in ("quit", "exit"):
            break
        if not prompt.strip():
            continue
        prompt_ids = tok.encode(prompt)
        if len(prompt_ids) == 0:
            print("(empty after tokenization, try different input)")
            continue
        out_ids = sample_generate(model, prompt_ids, max_new_tokens=args.max_new_tokens,
                                   temperature=args.temperature, top_k=args.top_k,
                                   top_p=args.top_p, rng=rng)
        print(tok.decode(out_ids))


def cmd_attn_viz(args):
    from loom.attn_viz import render_attention_html
    model, tok = _load_for_inference(args.checkpoint, args.tokenizer)
    if not args.prompt.strip():
        print("ERROR: --prompt must be non-empty", file=sys.stderr)
        sys.exit(1)
    n_tokens = len(tok.encode(args.prompt))
    if n_tokens > model.block_size:
        print(f"Note: prompt encodes to {n_tokens} tokens; only the last "
              f"{model.block_size} (block_size) are shown.")
    html = render_attention_html(model, tok, args.prompt)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"Wrote attention visualization to {args.out}")


def cmd_gradcheck(args):
    ok = gradcheck_mod.run_all()
    sys.exit(0 if ok else 1)


def cmd_demo(args):
    import subprocess
    script = args.script or "./demo.sh"
    subprocess.run(["bash", script], check=True)


def build_parser():
    p = argparse.ArgumentParser(prog="loom", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    tt = sub.add_parser("train-tokenizer", help="train a BPE tokenizer")
    tt.add_argument("--corpus", default="data/corpus.txt")
    tt.add_argument("--vocab-size", type=int, default=512)
    tt.add_argument("--out", default="tokenizer.json")
    tt.add_argument("--verbose", action="store_true")
    tt.set_defaults(func=cmd_train_tokenizer)

    tr = sub.add_parser("train", help="train a GPT model")
    tr.add_argument("--corpus", default="data/corpus.txt")
    tr.add_argument("--tokenizer", default="tokenizer.json")
    tr.add_argument("--out", default="checkpoint.npz")
    tr.add_argument("--history-out", default=None)
    tr.add_argument("--steps", type=int, default=800)
    tr.add_argument("--batch-size", type=int, default=16)
    tr.add_argument("--block-size", type=int, default=64)
    tr.add_argument("--d-model", type=int, default=64)
    tr.add_argument("--n-layer", type=int, default=3)
    tr.add_argument("--n-head", type=int, default=4)
    tr.add_argument("--lr", type=float, default=3e-3)
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--log-every", type=int, default=50)
    tr.set_defaults(func=cmd_train)

    ge = sub.add_parser("generate", help="sample text from a checkpoint")
    ge.add_argument("--checkpoint", default="checkpoint.npz")
    ge.add_argument("--tokenizer", default="tokenizer.json")
    ge.add_argument("--prompt", default="")
    ge.add_argument("--max-new-tokens", type=int, default=200)
    ge.add_argument("--temperature", type=float, default=0.8)
    ge.add_argument("--top-k", type=int, default=40)
    ge.add_argument("--top-p", type=float, default=None)
    ge.add_argument("--seed", type=int, default=None)
    ge.set_defaults(func=cmd_generate)

    ch = sub.add_parser("chat", help="interactive generation REPL")
    ch.add_argument("--checkpoint", default="checkpoint.npz")
    ch.add_argument("--tokenizer", default="tokenizer.json")
    ch.add_argument("--max-new-tokens", type=int, default=150)
    ch.add_argument("--temperature", type=float, default=0.8)
    ch.add_argument("--top-k", type=int, default=40)
    ch.add_argument("--top-p", type=float, default=None)
    ch.add_argument("--seed", type=int, default=None)
    ch.set_defaults(func=cmd_chat)

    av = sub.add_parser("attn-viz", help="render attention-weights HTML")
    av.add_argument("--checkpoint", default="checkpoint.npz")
    av.add_argument("--tokenizer", default="tokenizer.json")
    av.add_argument("--prompt", default="Old Maren sat at the loom")
    av.add_argument("--out", default="attention.html")
    av.set_defaults(func=cmd_attn_viz)

    gc = sub.add_parser("gradcheck", help="run gradient-check suite")
    gc.set_defaults(func=cmd_gradcheck)

    dm = sub.add_parser("demo", help="run demo.sh")
    dm.add_argument("--script", default=None)
    dm.set_defaults(func=cmd_demo)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
