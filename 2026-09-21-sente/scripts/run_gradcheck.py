#!/usr/bin/env python3
"""Runs every gradient check: individual ops, then the whole composed
network for both games' input/action dimensions. Exits non-zero if any
check fails a tolerance -- this must be green before any training run is
trusted (Phase 2 gate).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from sente.nn.layers import Linear, ReLU, Tanh, policy_cross_entropy_loss, mse_value_loss, masked_softmax
from sente.nn.gradcheck import check_layer_op, numerical_grad, rel_error, check_network
from sente.nn.network import PolicyValueNet
from sente.games.tictactoe import TicTacToe
from sente.games.connect4 import Connect4Jr

ALL_OK = True


def report(name, ok, err):
    global ALL_OK
    status = "OK " if ok else "FAIL"
    print(f"  [{status}] {name}: rel_err={err:.3e}")
    if not ok:
        ALL_OK = False


def check_relu():
    rng = np.random.default_rng(0)
    layer = ReLU()

    def fwd(x):
        return layer.forward(x)

    def bwd(x, dy):
        layer.forward(x)
        return layer.backward(dy)

    ok, err = check_layer_op("ReLU", fwd, bwd, (5, 7))
    report("ReLU", ok, err)


def check_tanh():
    layer = Tanh()

    def fwd(x):
        return layer.forward(x)

    def bwd(x, dy):
        layer.forward(x)
        return layer.backward(dy)

    ok, err = check_layer_op("Tanh", fwd, bwd, (5, 7))
    report("Tanh", ok, err)


def check_linear():
    rng = np.random.default_rng(0)
    layer = Linear(6, 4, rng)

    def fwd(x):
        return layer.forward(x)

    def bwd(x, dy):
        layer.forward(x)
        out = layer.backward(dy)
        return out

    ok, err = check_layer_op("Linear.dx", fwd, bwd, (5, 6))
    report("Linear (dx w.r.t. input)", ok, err)

    # also check dW, db directly
    rng2 = np.random.default_rng(1)
    x = rng2.standard_normal((5, 6))
    dy = rng2.standard_normal((5, 4))

    def loss_W(Wp):
        layer.W = Wp
        y = layer.forward(x)
        return float(np.sum(y * dy))

    layer.forward(x)
    layer.backward(dy)
    analytic_dW = layer.dW.copy()
    numeric, idxs = numerical_grad(loss_W, layer.W, eps=1e-5, n_samples=10, rng=rng2)
    err = rel_error(numeric.reshape(-1)[idxs], analytic_dW.reshape(-1)[idxs])
    report("Linear.dW", err < 1e-3, err)

    def loss_b(bp):
        layer.b = bp
        y = layer.forward(x)
        return float(np.sum(y * dy))

    numeric, idxs = numerical_grad(loss_b, layer.b, eps=1e-5, n_samples=layer.b.size, rng=rng2)
    err = rel_error(numeric.reshape(-1)[idxs], layer.db.reshape(-1)[idxs])
    report("Linear.db", err < 1e-3, err)


def check_policy_loss():
    rng = np.random.default_rng(2)
    N, A = 4, 6
    logits = rng.standard_normal((N, A))
    mask = rng.random((N, A)) > 0.4
    for i in range(N):
        if not mask[i].any():
            mask[i, 0] = True
    target = mask.astype(np.float64)
    target /= target.sum(axis=1, keepdims=True)

    def f(lg):
        loss, _ = policy_cross_entropy_loss(lg, mask, target)
        return loss

    loss, dlogits = policy_cross_entropy_loss(logits, mask, target)
    numeric, idxs = numerical_grad(f, logits, eps=1e-5, n_samples=logits.size, rng=rng)
    err = rel_error(numeric.reshape(-1)[idxs], dlogits.reshape(-1)[idxs])
    report("policy_cross_entropy_loss", err < 1e-3, err)

    # illegal-action gradient must be ~0
    illegal_grad = np.abs(dlogits[~mask]).max() if (~mask).any() else 0.0
    report("policy loss illegal-action grad ~ 0", illegal_grad < 1e-6, illegal_grad)


def check_value_loss():
    rng = np.random.default_rng(3)
    N = 5
    pred = rng.uniform(-1, 1, size=N)
    target = rng.uniform(-1, 1, size=N)

    def f(p):
        loss, _ = mse_value_loss(p, target)
        return loss

    loss, dpred = mse_value_loss(pred, target)
    numeric, idxs = numerical_grad(f, pred, eps=1e-5, n_samples=N, rng=rng)
    err = rel_error(numeric.reshape(-1)[idxs], dpred.reshape(-1)[idxs])
    report("mse_value_loss", err < 1e-3, err)


def check_full_network(game, label):
    net = PolicyValueNet(game.input_dim, game.action_size, hidden_sizes=(32, 32), seed=42)
    results = check_network(net, game.input_dim, game.action_size, batch=4, n_param_samples=5, seed=7)
    worst = max(err for _, err, _ in results)
    all_ok = all(ok for _, _, ok in results)
    report(f"PolicyValueNet[{label}] all {len(results)} param-grad checks", all_ok, worst)
    for name, err, ok in results:
        if not ok:
            print(f"      -> FAILING: {name} err={err:.3e}")


if __name__ == "__main__":
    print("Running gradient checks (finite differences vs hand-derived backward)...")
    print("-- primitive ops --")
    check_relu()
    check_tanh()
    check_linear()
    check_policy_loss()
    check_value_loss()
    print("-- full composed network --")
    check_full_network(TicTacToe, "tictactoe")
    check_full_network(Connect4Jr, "connect4jr")

    print()
    if ALL_OK:
        print("ALL GRADIENT CHECKS PASSED.")
        sys.exit(0)
    else:
        print("GRADIENT CHECK FAILURES -- do not trust training until fixed.")
        sys.exit(1)
