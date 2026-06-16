"""Loss functions over Cotangent ``Value`` graphs.

All losses return a single scalar ``Value`` so ``.backward()`` works directly.
Multi-class uses a numerically-stable log-sum-exp softmax cross-entropy.
"""

from __future__ import annotations

from engine import Value


def mse(pred: list[Value], target: list[float]) -> Value:
    """Mean squared error over a batch of scalar predictions."""
    if not pred:
        raise ValueError("mse needs at least one element")
    if len(pred) != len(target):
        raise ValueError("pred/target length mismatch")
    total = Value(0.0)
    for p, t in zip(pred, target):
        d = p - t
        total = total + d * d
    return total * (1.0 / len(pred))


def binary_cross_entropy(logits: list[Value], target: list[float]) -> Value:
    """BCE with logits (applies sigmoid internally, stable form).

    For label y in {0,1} and logit z:  loss = softplus(z) - y*z
    where softplus(z) = log(1+exp(z)) computed stably as max(z,0)+log(1+exp(-|z|)).
    """
    if not logits:
        raise ValueError("binary_cross_entropy needs at least one element")
    if len(logits) != len(target):
        raise ValueError("logits/target length mismatch")
    total = Value(0.0)
    for z, y in zip(logits, target):
        # stable softplus via Value ops: relu(z) + log(1 + exp(-|z|))
        # -|z| = -(relu(z) + relu(-z))
        abs_z = z.relu() + (-z).relu()
        softplus = z.relu() + (1.0 + (-abs_z).exp()).log()
        total = total + softplus - y * z
    return total * (1.0 / len(logits))


def _softmax_logsumexp(logits: list[Value]) -> tuple[Value, float]:
    """Return (logsumexp Value, max_const) computed stably."""
    m = max(v.data for v in logits)
    shifted = [v - m for v in logits]
    s = Value(0.0)
    for v in shifted:
        s = s + v.exp()
    return s.log() + m, m


def softmax_cross_entropy(logits: list[Value], target_idx: int) -> Value:
    """Softmax cross-entropy for a single example given the true class index.

    loss = logsumexp(logits) - logits[target_idx]
    """
    if not (0 <= target_idx < len(logits)):
        raise ValueError("target_idx out of range")
    lse, _ = _softmax_logsumexp(logits)
    return lse - logits[target_idx]


def softmax_probs(logits: list[float]) -> list[float]:
    """Plain-float softmax for inference/visualization (stable)."""
    m = max(logits)
    exps = [pow(2.718281828459045, x - m) for x in logits]
    s = sum(exps)
    return [e / s for e in exps]
