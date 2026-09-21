"""Central finite-difference gradient checker. Every op's hand-derived
backward pass is checked here against numerical central differences
before any of it is trusted for real training, the same rigor this
repo's other from-scratch-backprop builds (Cotangent, the Loom builds)
apply.

Two levels are checked:
  1. Individual primitive ops (Linear, ReLU, Tanh, the two losses) in
     isolation, via `check_layer_op`.
  2. The whole composed PolicyValueNet's parameter gradients (every
     Linear layer's W and b, trunk and both heads) against the finite
     difference of the *total* scalar loss, via `check_network`.
"""

from __future__ import annotations
import numpy as np


def numerical_grad(f, x: np.ndarray, eps: float = 1e-5, n_samples: int = None, rng=None):
    """f: array -> scalar. Returns a numeric gradient array shaped like x,
    computed by central differences. If n_samples is given, only that many
    random coordinates are perturbed (others left at 0) -- used to keep
    whole-network checks fast; the coordinates actually checked are then
    compared against the analytic gradient at those same coordinates only.
    """
    grad = np.zeros_like(x, dtype=np.float64)
    flat = x.reshape(-1)
    n = flat.shape[0]
    if n_samples is None or n_samples >= n:
        idxs = np.arange(n)
    else:
        rng = rng or np.random.default_rng(0)
        idxs = rng.choice(n, size=n_samples, replace=False)
    gflat = grad.reshape(-1)
    for i in idxs:
        orig = flat[i]
        flat[i] = orig + eps
        fp = f(x)
        flat[i] = orig - eps
        fm = f(x)
        flat[i] = orig
        gflat[i] = (fp - fm) / (2 * eps)
    return grad, idxs


def rel_error(a: np.ndarray, b: np.ndarray) -> float:
    num = np.abs(a - b)
    den = np.maximum(np.abs(a) + np.abs(b), 1e-8)
    return float(np.max(num / den))


def check_layer_op(name, forward_fn, backward_fn, x_shape, seed=0, eps=1e-5, tol=1e-3):
    """Generic check for a stateless-ish elementwise/matmul op given as
    forward_fn(x)->y and backward_fn(x, dy)->dx, treating dy as all-ones
    reduced to a scalar sum (so backward_fn's output is exactly d(sum(y))/dx).
    """
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(x_shape)

    def scalar_f(xv):
        return float(np.sum(forward_fn(xv)))

    numeric, idxs = numerical_grad(scalar_f, x, eps=eps)
    y = forward_fn(x)
    dy = np.ones_like(y)
    analytic = backward_fn(x, dy)
    err = rel_error(numeric.reshape(-1)[idxs], analytic.reshape(-1)[idxs])
    ok = err < tol
    return ok, err


def check_network(net, input_dim, action_size, batch=4, n_param_samples=6, seed=1, eps=1e-5, tol=1e-2):
    """Checks every Linear layer's W and b gradient in the composed
    network against finite differences of the *total* training loss
    (policy CE + value MSE + L2), at a random batch of legal-masked
    inputs and random targets. This is the strongest check: it exercises
    the exact forward/backward path used during real training, including
    both heads rejoining the shared trunk.
    """
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((batch, input_dim))
    legal_mask = rng.random((batch, action_size)) > 0.3
    # guarantee at least one legal move per row
    for i in range(batch):
        if not legal_mask[i].any():
            legal_mask[i, rng.integers(action_size)] = True
    policy_target = legal_mask.astype(np.float64)
    policy_target = policy_target / policy_target.sum(axis=1, keepdims=True)
    value_target = rng.uniform(-1, 1, size=batch)

    def total_loss():
        losses = net.loss_and_backward(x, legal_mask, policy_target, value_target)
        return losses["total"]

    results = []
    for i, layer in enumerate(net.all_layers()):
        params = layer.params()
        if not params:
            continue
        # analytic grads: run backward once (fresh) to populate dW/db
        total_loss()
        grads = layer.grads()
        for name, p in params.items():
            g = grads[name]
            # `p` is the exact array object the layer holds, so mutating it
            # in place (which numerical_grad does) and recomputing the loss
            # perturbs the real parameter used by forward().
            numeric, idxs = numerical_grad(
                lambda _arr: total_loss(), p, eps=eps,
                n_samples=min(n_param_samples, p.size), rng=rng,
            )
            err = rel_error(numeric.reshape(-1)[idxs], g.reshape(-1)[idxs])
            results.append((f"layer{i}.{name}", err, err < tol))
    return results
