"""
Shared numpy-backed math primitives, plus a generic finite-difference
gradient checker used by tests/test_gradcheck.py to verify every
hand-derived backward() in layers.py against numerical gradients.
"""
import numpy as np

GELU_C = np.sqrt(2.0 / np.pi)


def gelu_forward(x):
    """GPT-2's tanh approximation of GELU."""
    inner = GELU_C * (x + 0.044715 * x ** 3)
    t = np.tanh(inner)
    return 0.5 * x * (1.0 + t), (x, t)


def gelu_backward(dout, cache):
    x, t = cache
    inner_grad = GELU_C * (1.0 + 3 * 0.044715 * x ** 2)
    dtanh = (1.0 - t ** 2) * inner_grad
    dx = dout * (0.5 * (1.0 + t) + 0.5 * x * dtanh)
    return dx


def softmax(x, axis=-1):
    x = x - np.max(x, axis=axis, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=axis, keepdims=True)


def softmax_backward(dout, p, axis=-1):
    """Given p = softmax(s) and dL/dp, return dL/ds."""
    dot = np.sum(p * dout, axis=axis, keepdims=True)
    return p * (dout - dot)


def cross_entropy_from_logits(logits, targets, ignore_index=None):
    """
    logits: (N, V)  targets: (N,) int
    Returns (loss_scalar_mean, dlogits (N,V))
    ignore_index: target value to exclude from the loss/grad (e.g. padding).
    """
    N, V = logits.shape
    p = softmax(logits, axis=-1)
    mask = np.ones(N, dtype=np.float64)
    if ignore_index is not None:
        mask = (targets != ignore_index).astype(np.float64)
    n_valid = max(mask.sum(), 1.0)

    idx = np.arange(N)
    safe_targets = np.where(targets == ignore_index, 0, targets) if ignore_index is not None else targets
    correct_p = p[idx, safe_targets]
    losses = -np.log(np.clip(correct_p, 1e-12, None)) * mask
    loss = losses.sum() / n_valid

    dlogits = p.copy()
    dlogits[idx, safe_targets] -= 1.0
    dlogits *= mask[:, None]
    dlogits /= n_valid
    return loss, dlogits


def numerical_gradient(f, x, eps=1e-4):
    """Central finite-difference gradient of scalar-valued f w.r.t. array x."""
    grad = np.zeros_like(x, dtype=np.float64)
    it = np.nditer(x, flags=["multi_index"])
    for _ in it:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps
        f_plus = f()
        x[idx] = orig - eps
        f_minus = f()
        x[idx] = orig
        grad[idx] = (f_plus - f_minus) / (2 * eps)
    return grad
