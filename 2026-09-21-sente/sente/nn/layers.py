"""Every primitive op used by the policy/value network, each with a
hand-derived forward pass AND a hand-derived backward pass. NumPy is used
only as a dense-array/BLAS substrate (matmul, elementwise ops) -- there is
no autograd anywhere: every `backward` here is a closed-form derivative
written out by hand and checked against finite differences in
`gradcheck.py` before any of this is trusted for real training.

All layers operate on batches: x has shape (N, in_dim).
"""

from __future__ import annotations
import numpy as np


class Layer:
    """Base class: a layer owns its own parameters (if any) and their
    gradients, and caches whatever it needs from forward() to compute
    backward()."""

    def params(self):
        return {}

    def grads(self):
        return {}

    def forward(self, x):
        raise NotImplementedError

    def backward(self, dy):
        raise NotImplementedError


class Linear(Layer):
    """y = x @ W + b.  x: (N, in), W: (in, out), b: (out,), y: (N, out)."""

    def __init__(self, in_dim: int, out_dim: int, rng: np.random.Generator):
        # He initialization (fine for the ReLU trunk; the tiny output
        # heads use it too, which is harmless at this scale).
        scale = np.sqrt(2.0 / in_dim)
        self.W = (rng.standard_normal((in_dim, out_dim)) * scale).astype(np.float64)
        self.b = np.zeros(out_dim, dtype=np.float64)
        self.dW = np.zeros_like(self.W)
        self.db = np.zeros_like(self.b)
        self._x = None

    def forward(self, x):
        self._x = x
        return x @ self.W + self.b

    def backward(self, dy):
        # dL/dW = x^T @ dy ; dL/db = sum over batch of dy ; dL/dx = dy @ W^T
        self.dW = self._x.T @ dy
        self.db = dy.sum(axis=0)
        dx = dy @ self.W.T
        return dx

    def params(self):
        return {"W": self.W, "b": self.b}

    def grads(self):
        return {"W": self.dW, "b": self.db}

    def set_params(self, W, b):
        self.W = W
        self.b = b


class ReLU(Layer):
    def __init__(self):
        self._mask = None

    def forward(self, x):
        self._mask = x > 0
        return x * self._mask

    def backward(self, dy):
        return dy * self._mask


class Tanh(Layer):
    def __init__(self):
        self._y = None

    def forward(self, x):
        self._y = np.tanh(x)
        return self._y

    def backward(self, dy):
        return dy * (1.0 - self._y ** 2)


def masked_softmax(logits: np.ndarray, legal_mask: np.ndarray) -> np.ndarray:
    """Softmax over `logits` (N, A) with illegal actions (legal_mask False)
    forced to (numerically) zero probability. Implemented by additively
    masking to a large negative constant *before* the max-subtraction
    softmax, which is why the backward pass below is exactly the standard
    softmax-cross-entropy gradient: adding a constant that does not depend
    on the logits is a linear (slope-1) op, so d(masked_logits)/d(logits)
    is the identity and no extra chain-rule term is needed.
    """
    NEG = -1e9
    masked = np.where(legal_mask, logits, NEG)
    m = masked.max(axis=1, keepdims=True)
    ex = np.exp(masked - m)
    ex = ex * legal_mask  # belt-and-suspenders: zero out any residual mass
    denom = ex.sum(axis=1, keepdims=True)
    denom = np.maximum(denom, 1e-12)
    return ex / denom


def policy_cross_entropy_loss(logits: np.ndarray, legal_mask: np.ndarray, target: np.ndarray):
    """Cross-entropy between the MCTS visit-count target distribution and
    the network's masked-softmax policy. Returns (loss_scalar, dlogits).

    target: (N, A), rows sum to 1 over legal actions, 0 at illegal actions.

    Derivation: with p = softmax(masked_logits) and L = -sum(target*log p)
    averaged over the batch, dL/d(masked_logits) = (p - target) / N. Since
    masking is additive-constant (see masked_softmax docstring),
    dL/d(logits) = dL/d(masked_logits) exactly.
    """
    probs = masked_softmax(logits, legal_mask)
    N = logits.shape[0]
    logp = np.log(np.maximum(probs, 1e-12))
    loss = -np.sum(target * logp) / N
    dlogits = (probs - target) / N
    return loss, dlogits


def mse_value_loss(pred: np.ndarray, target: np.ndarray):
    """pred, target: (N,) or (N,1). Returns (loss_scalar, dpred)."""
    pred = pred.reshape(-1)
    target = target.reshape(-1)
    N = pred.shape[0]
    diff = pred - target
    loss = np.mean(diff ** 2)
    dpred = (2.0 / N) * diff
    return loss, dpred.reshape(-1, 1)
