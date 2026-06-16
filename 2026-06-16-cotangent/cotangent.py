#!/usr/bin/env python3
"""Cotangent CLI — reverse-mode autodiff engine + neural-net trainer.

Subcommands:
  gradcheck   Gradient-check the engine's analytic gradients vs finite differences.
  train       Train an MLP on a synthetic dataset; print metrics.
  viz         Train and emit an interactive training-playground HTML.
  graph       Emit a computation-graph HTML for a sample expression.
  demo        Run a quick end-to-end showcase of everything.
"""

from __future__ import annotations

import argparse
import sys

import data
import gradcheck as gc
import losses
import train as trainer
from engine import Value
from nn import MLP
from viz import graph_html, playground_html


# --------------------------------------------------------------------------- #
def _gradcheck_suite():
    """A representative battery of functions covering every primitive op."""
    suite = [
        ("add",        lambda x: x[0] + x[1],                       [1.5, -2.0]),
        ("mul",        lambda x: x[0] * x[1],                       [1.5, -2.0]),
        ("sub",        lambda x: x[0] - x[1],                       [1.0, 2.0]),
        ("div",        lambda x: x[0] / x[1],                       [3.0, 1.7]),
        ("reuse x*x",  lambda x: x[0] * x[0],                       [2.3]),
        ("reuse x+x",  lambda x: x[0] + x[0],                       [2.3]),
        ("pow_const",  lambda x: x[0] ** 3,                         [1.4]),
        ("a**b",       lambda x: x[0] ** x[1],                      [1.5, 2.2]),
        ("tanh",       lambda x: x[0].tanh(),                       [0.7]),
        ("relu",       lambda x: x[0].relu(),                       [1.2]),
        ("sigmoid",    lambda x: x[0].sigmoid(),                    [0.3]),
        ("exp",        lambda x: x[0].exp(),                        [0.5]),
        ("log",        lambda x: x[0].log(),                        [2.0]),
        ("composite",  lambda x: (x[0] * x[1] + x[0].tanh()).sigmoid()
                                 * (x[1].exp() + 1.0),              [0.6, 0.9]),
        ("neg+rsub",   lambda x: 2.0 - (-x[0]) + 3.0 * x[1],        [1.1, 2.2]),
        ("loss:mse",   lambda x: losses.mse(x, [1.0, 2.0]),         [0.3, 2.5]),
        ("loss:bce",   lambda x: losses.binary_cross_entropy(x, [1.0, 0.0]),
                                                                    [0.7, -1.1]),
        ("loss:softmax_ce",
                       lambda x: losses.softmax_cross_entropy(x, 1), [0.5, -0.3, 1.2]),
    ]
    return suite


def cmd_gradcheck(args):
    tol = args.tol
    worst = 0.0
    failed = 0
    for name, f, xs in _gradcheck_suite():
        rep = gc.check(f, xs)
        worst = max(worst, rep["max_rel_error"])
        ok = rep["max_rel_error"] < tol
        failed += not ok
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {name:14s} max_rel_error={rep['max_rel_error']:.2e}")
        if args.verbose:
            print(gc.report_str(name, rep))
    print(f"\nworst max_rel_error = {worst:.2e}  (tolerance {tol:.0e})")
    if failed:
        print(f"FAILED {failed} check(s)")
        return 1
    print("All gradient checks passed.")
    return 0


def _build_model(args):
    hidden = [int(h) for h in args.hidden.split(",") if h.strip()]
    sizes = [2] + hidden + [1]
    return MLP(sizes, hidden_act=args.activation, out_act="linear", seed=args.seed)


def cmd_train(args):
    X, y = data.get(args.dataset, n=args.n, seed=args.data_seed)
    model = _build_model(args)
    print(f"dataset={args.dataset}  n={len(X)}  {model}  optimizer={args.optimizer}")
    hist = trainer.train(model, X, y, epochs=args.epochs, batch_size=args.batch,
                         optimizer=args.optimizer, lr=args.lr, seed=args.seed,
                         log=print)
    print(f"\nfinal: loss={hist['loss'][-1]:.4f}  acc={hist['acc'][-1]:.3f}")
    return 0


def cmd_viz(args):
    X, y = data.get(args.dataset, n=args.n, seed=args.data_seed)
    model = _build_model(args)
    box = data.bounds(X)
    snap_every = max(1, args.epochs // args.frames)
    print(f"training {model} on {args.dataset} ({args.epochs} epochs)...")
    hist = trainer.train(model, X, y, epochs=args.epochs, batch_size=args.batch,
                         optimizer=args.optimizer, lr=args.lr, seed=args.seed,
                         snapshot_box=box, snapshot_every=snap_every,
                         snapshot_res=args.res, log=print)
    out = args.out or f"playground_{args.dataset}.html"
    with open(out, "w") as fh:
        fh.write(playground_html(hist, X, y, box, args.dataset, repr(model)))
    print(f"\nfinal acc={hist['acc'][-1]:.3f}  ->  wrote {out} "
          f"({len(hist['snapshots'])} snapshots)")
    return 0


def cmd_compare(args):
    """Train identical nets with Adam and SGD; report convergence side by side."""
    X, y = data.get(args.dataset, n=args.n, seed=args.data_seed)
    hidden = [int(h) for h in args.hidden.split(",") if h.strip()]
    sizes = [2] + hidden + [1]
    results = {}
    for opt in ("adam", "sgd"):
        model = MLP(sizes, hidden_act=args.activation, out_act="linear",
                    seed=args.seed)
        hist = trainer.train(model, X, y, epochs=args.epochs, batch_size=args.batch,
                             optimizer=opt, lr=args.lr, seed=args.seed)
        results[opt] = hist
    print(f"dataset={args.dataset}  sizes={sizes}  epochs={args.epochs}\n")
    print(f"{'epoch':>6} | {'adam loss':>10} {'adam acc':>9} | "
          f"{'sgd loss':>10} {'sgd acc':>9}")
    print("-" * 56)
    step = max(1, args.epochs // 10)
    marks = sorted(set(list(range(0, args.epochs, step)) + [args.epochs - 1]))
    for e in marks:
        a, s = results["adam"], results["sgd"]
        print(f"{e+1:>6} | {a['loss'][e]:>10.4f} {a['acc'][e]:>9.3f} | "
              f"{s['loss'][e]:>10.4f} {s['acc'][e]:>9.3f}")
    print("-" * 56)
    print(f"final accuracy:  adam={results['adam']['acc'][-1]:.3f}  "
          f"sgd={results['sgd']['acc'][-1]:.3f}")
    return 0


def cmd_graph(args):
    # Build a small illustrative expression with named leaves.
    a = Value(args.a, label="a")
    b = Value(args.b, label="b")
    c = Value(args.c, label="c")
    out = (a * b + c).tanh()
    out.label = "out"
    expr = "out = tanh(a*b + c)"
    fn = args.out or "graph.html"
    with open(fn, "w") as fh:
        fh.write(graph_html(out, expr=expr))
    print(f"expr: {expr}   with a={args.a}, b={args.b}, c={args.c}")
    print(f"forward value = {out.data:.4f}")
    print(f"wrote {fn}")
    return 0


def cmd_demo(args):
    print("=" * 60)
    print("COTANGENT DEMO")
    print("=" * 60)
    print("\n[1] Gradient check (analytic vs finite differences):")
    rc = cmd_gradcheck(argparse.Namespace(tol=1e-5, verbose=False))
    print("\n[2] Train a 2-16-16-1 MLP on 'moons':")
    X, y = data.get("moons", n=120, seed=1)
    model = MLP([2, 16, 16, 1], seed=42)
    hist = trainer.train(model, X, y, epochs=40, batch_size=16,
                         optimizer="adam", lr=0.05, seed=0, log=print)
    print(f"    -> final accuracy {hist['acc'][-1]*100:.1f}%")
    print("\n[3] Emit a computation-graph HTML (graph.html):")
    cmd_graph(argparse.Namespace(a=1.5, b=-2.0, c=3.0, out="graph.html"))
    print("\nDemo complete.")
    return rc


def build_parser():
    p = argparse.ArgumentParser(prog="cotangent", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gradcheck", help="verify gradients vs finite differences")
    g.add_argument("--tol", type=float, default=1e-5)
    g.add_argument("--verbose", action="store_true")
    g.set_defaults(func=cmd_gradcheck)

    common_model = argparse.ArgumentParser(add_help=False)
    common_model.add_argument("--hidden", default="16,16",
                              help="comma-separated hidden layer sizes")
    common_model.add_argument("--activation", default="tanh",
                              choices=["tanh", "relu", "sigmoid"])
    common_model.add_argument("--optimizer", default="adam", choices=["adam", "sgd"])
    common_model.add_argument("--lr", type=float, default=None)
    common_model.add_argument("--epochs", type=int, default=80)
    common_model.add_argument("--batch", type=int, default=16)
    common_model.add_argument("--n", type=int, default=160)
    common_model.add_argument("--seed", type=int, default=42)
    common_model.add_argument("--data-seed", type=int, default=1, dest="data_seed")
    common_model.add_argument("--dataset", default="moons",
                              choices=["xor", "moons", "circles", "spiral"])

    t = sub.add_parser("train", parents=[common_model], help="train an MLP")
    t.set_defaults(func=cmd_train)

    v = sub.add_parser("viz", parents=[common_model],
                       help="train and emit playground HTML")
    v.add_argument("--out", default=None)
    v.add_argument("--frames", type=int, default=24, help="number of snapshots")
    v.add_argument("--res", type=int, default=36, help="boundary grid resolution")
    v.set_defaults(func=cmd_viz)

    c = sub.add_parser("compare", parents=[common_model],
                       help="train Adam vs SGD side by side")
    c.set_defaults(func=cmd_compare)

    gr = sub.add_parser("graph", help="emit a computation-graph HTML")
    gr.add_argument("--a", type=float, default=1.5)
    gr.add_argument("--b", type=float, default=-2.0)
    gr.add_argument("--c", type=float, default=3.0)
    gr.add_argument("--out", default=None)
    gr.set_defaults(func=cmd_graph)

    d = sub.add_parser("demo", help="quick end-to-end showcase")
    d.set_defaults(func=cmd_demo)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
