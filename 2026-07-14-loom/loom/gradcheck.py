"""Finite-difference gradient checking.

This is what proves the hand-written backward() methods in nn.py/model.py
are the real analytic gradient and not just plausible-looking matrix code:
every checked parameter's backprop gradient is compared against a central
finite-difference numerical gradient of the actual scalar loss.
"""
import numpy as np

from loom.nn import softmax_cross_entropy


def numerical_grad_sample(param, loss_fn, num_samples, eps, rng):
    """Central-difference gradient at `num_samples` random elements of `param`."""
    flat = param.value.reshape(-1)  # view into param.value (contiguous by construction)
    n = flat.size
    idxs = rng.choice(n, size=min(num_samples, n), replace=False)
    numeric = np.zeros(len(idxs))
    original = flat[idxs].copy()
    for j, i in enumerate(idxs):
        flat[i] = original[j] + eps
        loss_plus = loss_fn()
        flat[i] = original[j] - eps
        loss_minus = loss_fn()
        flat[i] = original[j]
        numeric[j] = (loss_plus - loss_minus) / (2 * eps)
    return idxs, numeric


def gradcheck_model(model, ids, targets, num_samples=4, eps=1e-4, atol=1e-4, rtol=2e-2, seed=0):
    """Returns a list of dicts, one per named parameter, with max abs/rel
    error over the sampled elements. Raises AssertionError if any parameter
    fails the |analytic - numeric| <= atol + rtol*|numeric| criterion.
    """
    rng = np.random.RandomState(seed)

    def loss_fn():
        logits, _ = model.forward(ids)
        loss, _ = softmax_cross_entropy(logits, targets)
        return loss

    model.zero_grad()
    logits, _ = model.forward(ids)
    loss, dlogits = softmax_cross_entropy(logits, targets)
    model.backward(dlogits)

    results = []
    failures = []
    for pi, param in enumerate(model.parameters()):
        idxs, numeric = numerical_grad_sample(param, loss_fn, num_samples, eps, rng)
        analytic = param.grad.reshape(-1)[idxs]
        diff = np.abs(analytic - numeric)
        tol = atol + rtol * np.abs(numeric)
        ok = bool(np.all(diff <= tol))
        max_rel = float(np.max(diff / (np.abs(numeric) + 1e-8)))
        results.append(
            dict(param_index=pi, shape=list(param.value.shape), ok=ok,
                 max_abs_diff=float(np.max(diff)), max_rel_diff=max_rel)
        )
        if not ok:
            failures.append(results[-1])

    if failures:
        raise AssertionError(f"gradcheck failed for {len(failures)} parameter(s): {failures}")
    return results
