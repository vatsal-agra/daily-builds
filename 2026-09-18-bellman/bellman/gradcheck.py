"""Finite-difference verification of PolicyNet.backward(). Every
hand-derived gradient in this repo gets checked against numerical
differentiation before it's trusted for training (see the from-scratch
Transformer builds under prior LEDGER.md entries for the same discipline
applied to a much bigger autodiff engine) -- this is the same idea at the
scale REINFORCE's tiny policy network actually needs.

Checked quantity: d(advantage * log probs[action]) / d(param), for every
scalar parameter in W1, b1, W2, b2, compared to a central-difference
numerical estimate of the same thing.
"""
import math

from .reinforce import PolicyNet


def _loss(net, x, action, advantage):
    probs, _ = net.forward(x)
    return advantage * math.log(max(probs[action], 1e-12))


def _numerical_grad(net, param_matrix_or_vec, i, j, x, action, advantage, eps=1e-5):
    is_vec = j is None
    if is_vec:
        orig = param_matrix_or_vec[i]
        param_matrix_or_vec[i] = orig + eps
        plus = _loss(net, x, action, advantage)
        param_matrix_or_vec[i] = orig - eps
        minus = _loss(net, x, action, advantage)
        param_matrix_or_vec[i] = orig
    else:
        orig = param_matrix_or_vec[i][j]
        param_matrix_or_vec[i][j] = orig + eps
        plus = _loss(net, x, action, advantage)
        param_matrix_or_vec[i][j] = orig - eps
        minus = _loss(net, x, action, advantage)
        param_matrix_or_vec[i][j] = orig
    return (plus - minus) / (2 * eps)


def check(seed=0, tol=1e-4):
    net = PolicyNet(input_size=4, hidden_size=6, output_size=2, seed=seed)
    x = [0.3, -0.6, 0.1, -0.2]
    action = 1
    advantage = 2.5

    probs, cache = net.forward(x)
    grads = net.backward(cache, action, advantage)

    worst = 0.0
    checks = 0

    for name, matrix, grad_key in (("W1", net.W1, "dW1"), ("W2", net.W2, "dW2")):
        for i in range(len(matrix)):
            for j in range(len(matrix[i])):
                analytic = grads[grad_key][i][j]
                numeric = _numerical_grad(net, matrix, i, j, x, action, advantage)
                worst = max(worst, abs(analytic - numeric))
                checks += 1
                if abs(analytic - numeric) > tol:
                    raise AssertionError(
                        f"{name}[{i}][{j}]: analytic={analytic:.6f} numeric={numeric:.6f}"
                    )

    for name, vec, grad_key in (("b1", net.b1, "db1"), ("b2", net.b2, "db2")):
        for i in range(len(vec)):
            analytic = grads[grad_key][i]
            numeric = _numerical_grad(net, vec, i, None, x, action, advantage)
            worst = max(worst, abs(analytic - numeric))
            checks += 1
            if abs(analytic - numeric) > tol:
                raise AssertionError(f"{name}[{i}]: analytic={analytic:.6f} numeric={numeric:.6f}")

    return checks, worst


if __name__ == "__main__":
    n, worst = check()
    print(f"gradcheck OK: {n} parameters checked, max |analytic - numeric| = {worst:.2e}")
