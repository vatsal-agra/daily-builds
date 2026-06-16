"""Training harness for Cotangent MLPs on 2-D binary classification datasets.

Runs minibatched gradient descent, records loss/accuracy history, and can capture
decision-boundary snapshots for the visualizer.
"""

from __future__ import annotations

import math
import random
from typing import Callable

from engine import Value
from losses import binary_cross_entropy
from nn import MLP
from optim import Adam, Optimizer, SGD


def predict_logit(model: MLP, point: list[float]) -> float:
    """Forward pass returning the raw output logit as a float."""
    out = model([Value(point[0]), Value(point[1])])
    return out[0].data


def predict_prob(model: MLP, point: list[float]) -> float:
    z = predict_logit(model, point)
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def accuracy(model: MLP, X, y) -> float:
    correct = 0
    for point, label in zip(X, y):
        pred = 1 if predict_logit(model, point) > 0 else 0
        correct += int(pred == label)
    return correct / len(X)


def make_optimizer(name: str, params: list[Value], lr: float | None = None,
                   **kw) -> Optimizer:
    name = name.lower()
    if name == "adam":
        return Adam(params, lr=lr if lr is not None else 0.05, **kw)
    if name == "sgd":
        return SGD(params, lr=lr if lr is not None else 0.1, momentum=0.9, **kw)
    raise ValueError(f"unknown optimizer {name!r}")


def boundary_grid(model: MLP, box, res: int = 30) -> list[list[float]]:
    """Sample model probability over a res×res grid covering ``box``."""
    xmin, xmax, ymin, ymax = box
    grid = []
    for j in range(res):
        row = []
        for i in range(res):
            x = xmin + (xmax - xmin) * i / (res - 1)
            y = ymin + (ymax - ymin) * j / (res - 1)
            row.append(predict_prob(model, [x, y]))
        grid.append(row)
    return grid


def train(model: MLP, X, y, *, epochs: int = 100, batch_size: int = 32,
          optimizer: str = "adam", lr: float | None = None, seed: int = 0,
          snapshot_box=None, snapshot_every: int = 0, snapshot_res: int = 30,
          log: Callable[[str], None] | None = None) -> dict:
    """Train ``model`` and return a history dict.

    If ``snapshot_every > 0`` and ``snapshot_box`` is given, decision-boundary
    grids are captured for the visualizer.
    """
    if not X:
        raise ValueError("train() needs a non-empty dataset")
    if len(X) != len(y):
        raise ValueError("X and y length mismatch")
    rng = random.Random(seed)
    opt = make_optimizer(optimizer, model.parameters(), lr)
    history = {"loss": [], "acc": [], "snapshots": [], "snapshot_epochs": []}
    n = len(X)

    def maybe_snapshot(ep):
        if snapshot_every and snapshot_box is not None and ep % snapshot_every == 0:
            history["snapshots"].append(boundary_grid(model, snapshot_box, snapshot_res))
            history["snapshot_epochs"].append(ep)

    maybe_snapshot(0)
    for ep in range(1, epochs + 1):
        idx = list(range(n))
        rng.shuffle(idx)
        epoch_loss = 0.0
        nb = 0
        for start in range(0, n, batch_size):
            batch = idx[start:start + batch_size]
            opt.zero_grad()
            logits = []
            targets = []
            for bi in batch:
                out = model([Value(X[bi][0]), Value(X[bi][1])])
                logits.append(out[0])
                targets.append(float(y[bi]))
            loss = binary_cross_entropy(logits, targets)
            loss.backward()
            opt.step()
            epoch_loss += loss.data
            nb += 1
        avg_loss = epoch_loss / max(nb, 1)
        acc = accuracy(model, X, y)
        history["loss"].append(avg_loss)
        history["acc"].append(acc)
        if log and (ep == 1 or ep % max(1, epochs // 10) == 0 or ep == epochs):
            log(f"epoch {ep:4d}/{epochs}  loss={avg_loss:.4f}  acc={acc:.3f}")
        maybe_snapshot(ep)

    return history
