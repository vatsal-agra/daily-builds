"""Loom CLI: gradcheck / train / generate / chat / viz / info / demo.

Run as `python3 -m loom <command> ...` (or via the `./loom` wrapper script
in the project root).
"""
import argparse
import os
import sys
import time

from . import gradcheck as gc
from .attention_trace import export as export_attention
from .data import Dataset
from .generate import chat as chat_loop
from .generate import generate as generate_text
from .nn import GPT
from .tokenizer import CharTokenizer
from .train import load_checkpoint, train as run_training

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(PROJECT_ROOT, "corpus")
VIZ_DIR = os.path.join(PROJECT_ROOT, "viz")

PRESETS = {
    "quickstart": dict(dim=32, n_layer=2, n_head=2, block_size=32),
    "tiny": dict(dim=64, n_layer=2, n_head=4, block_size=64),
    "small": dict(dim=128, n_layer=4, n_head=4, block_size=96),
}

CORPUS_SETS = {
    "all": ["chronicle.txt", "lampwright.txt"],
    "chronicle": ["chronicle.txt"],
    "lampwright": ["lampwright.txt"],
    "quickstart": ["quickstart.txt"],
}


def load_corpus(name):
    if name in CORPUS_SETS:
        files = [os.path.join(CORPUS_DIR, f) for f in CORPUS_SETS[name]]
    elif os.path.isfile(name):
        files = [name]
    elif os.path.isfile(os.path.join(CORPUS_DIR, name)):
        files = [os.path.join(CORPUS_DIR, name)]
    else:
        raise ValueError(f"unknown corpus {name!r} (known sets: {sorted(CORPUS_SETS)}, or a file path)")
    parts = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            parts.append(f.read())
    return "\n\n".join(parts)


def cmd_gradcheck(args):
    print("== primitive op gradient checks (finite differences vs. analytic backward) ==")
    op_results = gc.check_ops()
    all_ok = True
    for name, ok, err in op_results:
        status = "PASS" if ok else "FAIL"
        all_ok &= ok
        print(f"  [{status}] {name:32s} max relative error {err:.2e}")

    print("\n== full-model gradient check (tiny GPT, forward -> loss -> backward) ==")
    ok, worst, n_checked = gc.check_model()
    all_ok &= ok
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {n_checked} sampled parameter entries across every tensor, "
          f"max relative error {worst:.2e}")

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    return 0 if all_ok else 1


def cmd_info(args):
    for name in sorted(CORPUS_SETS):
        text = load_corpus(name)
        vocab = len(set(text))
        print(f"corpus {name!r:14s} {len(text):7,d} chars, {vocab:3d} distinct characters")
    print("\npresets:")
    for name, cfg in PRESETS.items():
        print(f"  {name:12s} {cfg}")
    return 0


def build_model_and_data(args):
    text = load_corpus(args.corpus)
    tokenizer = CharTokenizer.from_text(text)
    ids = tokenizer.encode(text)
    preset = PRESETS[args.preset]
    block_size = args.block_size or preset["block_size"]
    dataset = Dataset(ids, block_size=block_size, val_fraction=args.val_fraction, seed=args.seed)
    model = GPT(vocab_size=tokenizer.vocab_size, dim=preset["dim"], n_layer=preset["n_layer"],
                n_head=preset["n_head"], max_len=block_size, seed=args.seed)
    return model, tokenizer, dataset, text


def cmd_train(args):
    for path in (args.out, args.log):
        if path and os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
    model, tokenizer, dataset, text = build_model_and_data(args)
    n_params = sum(p.data.size for p in model.parameters())
    print(f"corpus {args.corpus!r}: {len(text):,} chars, vocab {tokenizer.vocab_size}, "
          f"{n_params:,} parameters, block_size {model.max_len}")
    print(f"train tokens: {len(dataset.train_ids):,}  val tokens: {len(dataset.val_ids):,}")

    t0 = time.time()
    run_training(model, tokenizer, dataset, steps=args.steps, batch_size=args.batch_size,
                 lr=args.lr, warmup=args.warmup, grad_clip=args.grad_clip,
                 weight_decay=args.weight_decay, eval_interval=args.eval_interval,
                 eval_iters=args.eval_iters, log_path=args.log, ckpt_path=args.out)
    dt = time.time() - t0
    print(f"\ntrained {args.steps} steps in {dt:.1f}s ({args.steps / max(dt, 1e-9):.1f} steps/s)")
    if args.out:
        print(f"checkpoint written to {args.out}")
    if args.log:
        print(f"loss history written to {args.log}")
    return 0


def cmd_generate(args):
    model, tokenizer, meta = load_checkpoint(args.ckpt)
    text = generate_text(model, tokenizer, prompt=args.prompt, max_new_tokens=args.max_new_tokens,
                          temperature=args.temperature, top_k=args.top_k, top_p=args.top_p, seed=args.seed)
    print(text)
    return 0


def cmd_chat(args):
    model, tokenizer, meta = load_checkpoint(args.ckpt)
    chat_loop(model, tokenizer, max_new_tokens=args.max_new_tokens, temperature=args.temperature,
              top_k=args.top_k, top_p=args.top_p, seed=args.seed)
    return 0


def cmd_viz(args):
    model, tokenizer, meta = load_checkpoint(args.ckpt)
    loss_history = meta.get("extra", {}).get("history")
    out_path = args.out or os.path.join(VIZ_DIR, "attention.html")
    if len(args.prompt) > model.max_len:
        print(f"note: prompt is {len(args.prompt)} chars, truncating to the model's "
              f"context length ({model.max_len})")
    data = export_attention(model, tokenizer, args.prompt, out_path, loss_history=loss_history)
    print(f"exported {len(data['layers'])} layers x {model.n_head} heads over "
          f"{len(data['tokens'])} tokens -- self-contained visualizer written to {out_path}")
    print(f"open it directly in a browser (file://{os.path.abspath(out_path)})")
    return 0


def cmd_demo(args):
    print("=" * 70)
    print("LOOM DEMO -- from-scratch tensor autograd -> Transformer -> trained LM")
    print("=" * 70)

    print("\n--- 1. gradient-checking the autograd engine ---")
    if cmd_gradcheck(args) != 0:
        print("gradcheck failed, aborting demo")
        return 1

    print("\n--- 2. training a tiny GPT on the bundled corpus ---")
    train_args = argparse.Namespace(corpus="all", preset="tiny", block_size=None,
                                     val_fraction=0.1, seed=0, steps=args.steps,
                                     batch_size=16, lr=3e-3, warmup=max(20, args.steps // 20),
                                     grad_clip=1.0, weight_decay=0.0, eval_interval=max(1, args.steps // 10),
                                     eval_iters=10, out=args.ckpt, log=args.log)
    if cmd_train(train_args) != 0:
        return 1

    print("\n--- 3. generating text from the trained model ---")
    for prompt, temp in [("Mira", 0.7), ("The Warden", 0.9), ("", 1.0)]:
        gen_args = argparse.Namespace(ckpt=args.ckpt, prompt=prompt, max_new_tokens=160,
                                       temperature=temp, top_k=20, top_p=None, seed=0)
        print(f"\n  prompt={prompt!r} temperature={temp}:")
        cmd_generate(gen_args)

    print("\n--- 4. exporting attention weights + loss curve for the visualizer ---")
    viz_args = argparse.Namespace(ckpt=args.ckpt, prompt="Mira Ashgrove kept every wrong map",
                                   out=os.path.join(VIZ_DIR, "attention.html"))
    cmd_viz(viz_args)

    print("\nDEMO COMPLETE.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="loom", description="A from-scratch tensor autograd engine and GPT-style language model.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("gradcheck", help="finite-difference gradient-check the autograd engine and a real model")
    sp.set_defaults(func=cmd_gradcheck)

    sp = sub.add_parser("info", help="show bundled corpora and model presets")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("train", help="train a GPT on a bundled (or custom) corpus")
    sp.add_argument("--corpus", default="all", help="corpus set name (all/chronicle/lampwright/quickstart) or a file path")
    sp.add_argument("--preset", default="tiny", choices=sorted(PRESETS))
    sp.add_argument("--block-size", type=int, default=None, help="override preset context length")
    sp.add_argument("--val-fraction", type=float, default=0.1)
    sp.add_argument("--steps", type=int, default=1500)
    sp.add_argument("--batch-size", type=int, default=16)
    sp.add_argument("--lr", type=float, default=3e-3)
    sp.add_argument("--warmup", type=int, default=100)
    sp.add_argument("--grad-clip", type=float, default=1.0)
    sp.add_argument("--weight-decay", type=float, default=0.0)
    sp.add_argument("--eval-interval", type=int, default=100)
    sp.add_argument("--eval-iters", type=int, default=20)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", default=os.path.join(PROJECT_ROOT, "checkpoints", "model.npz"))
    sp.add_argument("--log", default=os.path.join(PROJECT_ROOT, "checkpoints", "loss_history.json"))
    sp.set_defaults(func=cmd_train)

    sp = sub.add_parser("generate", help="generate text from a trained checkpoint")
    sp.add_argument("--ckpt", default=os.path.join(PROJECT_ROOT, "checkpoints", "model.npz"))
    sp.add_argument("--prompt", default="")
    sp.add_argument("--max-new-tokens", type=int, default=300)
    sp.add_argument("--temperature", type=float, default=0.8)
    sp.add_argument("--top-k", type=int, default=None)
    sp.add_argument("--top-p", type=float, default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("chat", help="interactive REPL against a trained checkpoint")
    sp.add_argument("--ckpt", default=os.path.join(PROJECT_ROOT, "checkpoints", "model.npz"))
    sp.add_argument("--max-new-tokens", type=int, default=250)
    sp.add_argument("--temperature", type=float, default=0.8)
    sp.add_argument("--top-k", type=int, default=40)
    sp.add_argument("--top-p", type=float, default=0.95)
    sp.add_argument("--seed", type=int, default=None)
    sp.set_defaults(func=cmd_chat)

    sp = sub.add_parser("viz", help="export attention weights + loss curve for the HTML visualizer")
    sp.add_argument("--ckpt", default=os.path.join(PROJECT_ROOT, "checkpoints", "model.npz"))
    sp.add_argument("--prompt", required=True)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("demo", help="run the full pipeline end to end: gradcheck, train, generate, export viz")
    sp.add_argument("--steps", type=int, default=700)
    sp.add_argument("--ckpt", default=os.path.join(PROJECT_ROOT, "checkpoints", "demo_model.npz"))
    sp.add_argument("--log", default=os.path.join(PROJECT_ROOT, "checkpoints", "demo_loss_history.json"))
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    os.makedirs(os.path.join(PROJECT_ROOT, "checkpoints"), exist_ok=True)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename or e} "
              f"(if this is a checkpoint, run `train` first to produce one)", file=sys.stderr)
        return 1
    except (ValueError, AssertionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
