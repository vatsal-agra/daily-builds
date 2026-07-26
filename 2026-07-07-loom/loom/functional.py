"""Composite differentiable functions built entirely out of Tensor ops.

Because every function here is assembled from primitives in tensor.py,
their gradients come for free from the autograd engine - nothing in this
file hand-derives a backward pass.
"""
import numpy as np

from . import tensor as _tensor_mod
from .tensor import Tensor

NEG_INF = -1e9


def _stable_shift(x, axis):
    """Subtract the row max as a numerically-stabilizing constant shift
    (softmax/log_softmax are both shift-invariant, so this changes nothing
    mathematically) - applied directly to the raw array rather than as a
    differentiated graph node, since there is nothing to differentiate
    through: the true gradient is identical either way. Shared by softmax()
    and log_softmax() so a stability tweak only ever needs to happen once."""
    shifted_data = x.data - x.data.max(axis=axis, keepdims=True)
    # Read _grad_enabled through the module (not `from .tensor import
    # _grad_enabled`, which would freeze the value at import time and never
    # see no_grad() toggle it).
    if not _tensor_mod._grad_enabled:
        return Tensor(shifted_data)
    shifted = Tensor(shifted_data, requires_grad=x.requires_grad, _children=(x,), _op="shift")

    def _backward():
        if x.requires_grad:
            x._ensure_grad()
            x.grad += shifted.grad
    shifted._backward = _backward
    return shifted


def softmax(x, axis=-1):
    shifted = _stable_shift(x, axis)
    e = shifted.exp()
    denom = e.sum(axis=axis, keepdims=True)
    return e / denom


def log_softmax(x, axis=-1):
    shifted = _stable_shift(x, axis)
    logsumexp = shifted.exp().sum(axis=axis, keepdims=True).log()
    return shifted - logsumexp


def cross_entropy(logits, targets):
    """logits: Tensor of shape (N, V). targets: int array of shape (N,).
    Returns a scalar Tensor = mean negative log-likelihood."""
    n = logits.shape[0]
    logp = log_softmax(logits, axis=-1)
    picked = logp[np.arange(n), targets]
    return -picked.mean()


def layer_norm(x, gamma, beta, eps=1e-5):
    axis = -1
    mean = x.mean(axis=axis, keepdims=True)
    centered = x - mean
    var = (centered * centered).mean(axis=axis, keepdims=True)
    std = (var + eps) ** 0.5
    normed = centered / std
    return normed * gamma + beta


def gelu(x):
    # tanh-approximation GELU (as used in GPT-2), fully composed from
    # differentiable Tensor ops.
    c = 0.7978845608028654  # sqrt(2/pi)
    inner = (x + (x ** 3) * 0.044715) * c
    return x * 0.5 * (inner.tanh() + 1.0)


def causal_mask(seq_len):
    mask = np.triu(np.ones((seq_len, seq_len)), k=1) * NEG_INF
    return mask  # (T, T) additive mask, 0 where attend is allowed
