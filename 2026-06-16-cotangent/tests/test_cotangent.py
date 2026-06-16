"""Cotangent test suite — run with `python3 -m pytest` or `python3 tests/test_cotangent.py`.

Covers: every engine op via finite-difference gradient checks, loss gradients,
backprop edge cases (shared subexpressions, idempotent backward), numerical
stability, optimizer state, dataset shape/determinism, training convergence,
visualizer output, and CLI smoke. No third-party deps required.
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import data  # noqa: E402
import gradcheck as gc  # noqa: E402
import losses  # noqa: E402
from engine import Value  # noqa: E402
from nn import MLP, Neuron  # noqa: E402
from optim import SGD, Adam  # noqa: E402
from train import accuracy, train  # noqa: E402
from viz import graph_html, playground_html  # noqa: E402

TOL = 1e-5
_failures = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _failures.append(msg)


# --------------------------------------------------------------------------- #
def test_engine_gradients():
    print("[engine gradients vs finite differences]")
    cases = [
        ("add", lambda x: x[0] + x[1], [1.5, -2.0]),
        ("mul", lambda x: x[0] * x[1], [1.5, -2.0]),
        ("sub", lambda x: x[0] - x[1], [1.0, 2.0]),
        ("div", lambda x: x[0] / x[1], [3.0, 1.7]),
        ("x*x", lambda x: x[0] * x[0], [2.3]),
        ("x+x", lambda x: x[0] + x[0], [2.3]),
        ("pow_const", lambda x: x[0] ** 3, [1.4]),
        ("a**b", lambda x: x[0] ** x[1], [1.5, 2.2]),
        ("tanh", lambda x: x[0].tanh(), [0.7]),
        ("relu+", lambda x: x[0].relu(), [1.2]),
        ("relu-", lambda x: x[0].relu(), [-1.2]),
        ("sigmoid", lambda x: x[0].sigmoid(), [0.3]),
        ("exp", lambda x: x[0].exp(), [0.5]),
        ("log", lambda x: x[0].log(), [2.0]),
        ("composite", lambda x: (x[0] * x[1] + x[0].tanh()).sigmoid()
                                * (x[1].exp() + 1.0), [0.6, 0.9]),
        ("rsub/neg", lambda x: 2.0 - (-x[0]) + 3.0 * x[1], [1.1, 2.2]),
        ("rtruediv", lambda x: 2.0 / x[0], [1.3]),
    ]
    for name, f, xs in cases:
        rep = gc.check(f, xs)
        check(rep["max_rel_error"] < TOL,
              f"{name}: rel_err={rep['max_rel_error']:.2e}")


def test_loss_gradients():
    print("[loss gradients vs finite differences]")
    check(gc.check(lambda x: losses.mse(x, [1.0, 2.0]), [0.3, 2.5])["max_rel_error"] < TOL,
          "mse gradient")
    check(gc.check(lambda x: losses.binary_cross_entropy(x, [1.0, 0.0]),
                   [0.7, -1.1])["max_rel_error"] < TOL, "bce gradient")
    check(gc.check(lambda x: losses.softmax_cross_entropy(x, 1),
                   [0.5, -0.3, 1.2])["max_rel_error"] < TOL, "softmax_ce gradient")


def test_backprop_semantics():
    print("[backprop semantics]")
    # shared subexpression: f = (x*x) + (x*x); df/dx = 4x
    x = Value(3.0)
    y = x * x
    f = y + y
    f.backward()
    check(abs(x.grad - 4 * 3.0) < 1e-9, "shared subexpression grad = 4x")
    # idempotent backward
    x2 = Value(2.0)
    g = x2 * x2
    g.backward(); first = x2.grad
    g.backward(); second = x2.grad
    check(abs(first - second) < 1e-12 and abs(first - 4.0) < 1e-9,
          "backward() idempotent")
    # topo returns all nodes, inputs before outputs
    order = f.topo()
    check(order[-1] is f, "topo ends at root")


def test_numerical_stability():
    print("[numerical stability]")
    check(abs(losses.binary_cross_entropy([Value(1000.0)], [0.0]).data - 1000.0) < 1e-6,
          "BCE(logit=1000,y=0) ~= 1000 (no overflow)")
    check(Value(-1000.0).sigmoid().data == 0.0, "sigmoid(-1000)=0")
    check(abs(Value(1000.0).sigmoid().data - 1.0) < 1e-9, "sigmoid(1000)=1")


def test_domain_errors():
    print("[clear domain errors]")
    for label, fn in [
        ("log(-1)", lambda: Value(-1.0).log()),
        ("(-2)**v", lambda: Value(-2.0) ** Value(2.0)),
        ("bounds([])", lambda: data.bounds([])),
        ("mse([])", lambda: losses.mse([], [])),
    ]:
        try:
            fn()
            check(False, f"{label} should raise")
        except ValueError:
            check(True, f"{label} raises clear ValueError")


def test_optimizers():
    print("[optimizers]")
    # minimize f(w) = (w-3)^2 ; gradient 2(w-3)
    def run(opt_cls, **kw):
        w = Value(0.0)
        opt = opt_cls([w], **kw)
        for _ in range(500):
            opt.zero_grad()
            loss = (w - 3.0) * (w - 3.0)
            loss.backward()
            opt.step()
        return w.data
    check(abs(run(SGD, lr=0.05, momentum=0.9) - 3.0) < 1e-2, "SGD finds minimum")
    check(abs(run(Adam, lr=0.1) - 3.0) < 1e-2, "Adam finds minimum")
    # Adam updates internal moment state
    w = Value(0.0); a = Adam([w], lr=0.1)
    w.grad = 1.0; a.step()
    check(a.t == 1 and a.m[0] != 0.0 and a.v[0] != 0.0, "Adam tracks moments")


def test_nn_basics():
    print("[nn]")
    m = MLP([2, 4, 1], seed=0)
    check(len(m.parameters()) == (2 * 4 + 4) + (4 * 1 + 1), "param count correct")
    out = m([Value(0.5), Value(-0.5)])
    check(len(out) == 1 and isinstance(out[0], Value), "forward returns Values")
    m.zero_grad()
    check(all(p.grad == 0.0 for p in m.parameters()), "zero_grad clears")
    # determinism
    a = MLP([2, 3, 1], seed=7).parameters()[0].data
    b = MLP([2, 3, 1], seed=7).parameters()[0].data
    check(a == b, "init deterministic given seed")
    try:
        Neuron(2, activation="bogus")
        check(False, "bad activation should raise")
    except ValueError:
        check(True, "bad activation raises")


def test_datasets():
    print("[datasets]")
    for name in ("xor", "moons", "circles", "spiral"):
        X, y = data.get(name, n=60, seed=3)
        check(len(X) == 60 and len(y) == 60, f"{name} length")
        check(all(len(p) == 2 for p in X) and set(y) <= {0, 1}, f"{name} shape/labels")
    X1, _ = data.get("spiral", n=40, seed=5)
    X2, _ = data.get("spiral", n=40, seed=5)
    check(X1 == X2, "dataset deterministic given seed")


def test_training_converges():
    print("[training convergence]  (this is the slow part)")
    for name in ("xor", "moons", "circles"):
        X, y = data.get(name, n=80, seed=1)
        m = MLP([2, 12, 12, 1], seed=42)
        h = train(m, X, y, epochs=60, batch_size=16, optimizer="adam", lr=0.05, seed=0)
        check(h["acc"][-1] >= 0.95, f"{name} reaches >=95% (got {h['acc'][-1]:.2f})")
        check(h["loss"][-1] < h["loss"][0], f"{name} loss decreased")


def test_visualizers():
    print("[visualizers]")
    a, b, c = Value(1.5, label="a"), Value(-2.0, label="b"), Value(3.0, label="c")
    out = (a * b + c).tanh(); out.label = "out"
    html = graph_html(out, expr="out=tanh(a*b+c)")
    check(html.startswith("<!doctype html>") and "src=\"http" not in html,
          "graph html self-contained")
    check("\"nodes\"" in html and "\"edges\"" in html, "graph embeds data")
    # playground from a tiny real run
    X, y = data.get("moons", n=40, seed=1)
    m = MLP([2, 6, 1], seed=1)
    box = data.bounds(X)
    h = train(m, X, y, epochs=6, batch_size=16, optimizer="adam", lr=0.05,
              snapshot_box=box, snapshot_every=2, snapshot_res=10)
    ph = playground_html(h, X, y, box, "moons", repr(m))
    check(ph.startswith("<!doctype html>") and "snapshots" in ph,
          "playground html self-contained + embeds snapshots")
    check(len(h["snapshots"]) >= 3, "snapshots captured")


def test_cli_smoke():
    print("[cli smoke]")
    env = dict(os.environ)
    r = subprocess.run([sys.executable, "cotangent.py", "gradcheck"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    check(r.returncode == 0 and "All gradient checks passed" in r.stdout,
          "cli gradcheck exits 0")
    r2 = subprocess.run([sys.executable, "cotangent.py", "graph", "--out",
                         "/tmp/_ct_graph.html"], cwd=ROOT, capture_output=True, text=True)
    check(r2.returncode == 0 and os.path.exists("/tmp/_ct_graph.html"),
          "cli graph writes html")
    r3 = subprocess.run([sys.executable, "cotangent.py", "train", "--dataset", "xor",
                         "--epochs", "5", "--n", "40", "--hidden", "8"],
                        cwd=ROOT, capture_output=True, text=True)
    check(r3.returncode == 0 and "final" in r3.stdout, "cli train runs")


def main():
    tests = [
        test_engine_gradients, test_loss_gradients, test_backprop_semantics,
        test_numerical_stability, test_domain_errors, test_optimizers,
        test_nn_basics, test_datasets, test_training_converges,
        test_visualizers, test_cli_smoke,
    ]
    for t in tests:
        t()
    print("\n" + "=" * 50)
    if _failures:
        print(f"FAILED {len(_failures)} check(s):")
        for f in _failures:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


# pytest entry points
def test_all():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
