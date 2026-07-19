"""Central finite-difference gradient checking for the autodiff engine.

Every op in tensor.py is checked here: build a scalar loss from a small
random input, compute the analytic gradient via .backward(), then perturb
each input element by +-h and compare against (f(x+h) - f(x-h)) / 2h.
"""
import numpy as np
from .tensor import Tensor

np.random.seed(0)


def numeric_grad(f, x, h=1e-5):
    """f: Tensor -> scalar Tensor. Returns numeric gradient array same shape as x.data."""
    grad = np.zeros_like(x.data)
    it = np.nditer(x.data, flags=["multi_index"])
    while not it.finished:
        idx = it.multi_index
        orig = x.data[idx]
        x.data[idx] = orig + h
        plus = f(x).data.copy()
        x.data[idx] = orig - h
        minus = f(x).data.copy()
        x.data[idx] = orig
        grad[idx] = (plus - minus) / (2 * h)
        it.iternext()
    return grad


def analytic_grad(f, x):
    x.grad = None
    out = f(x)
    out.backward()
    return x.grad.copy()


def check(name, f, x, atol=1e-4, rtol=1e-2, verbose=False):
    """f must map a Tensor to a scalar Tensor (sum/mean the actual op output
    if needed) so a single backward() gives the full gradient."""
    ag = analytic_grad(f, x)
    ng = numeric_grad(f, x)
    diff = np.abs(ag - ng)
    denom = np.maximum(np.abs(ag), np.abs(ng)) + 1e-8
    rel = diff / denom
    ok = np.all((diff < atol) | (rel < rtol))
    if verbose or not ok:
        print(f"[{name}] max_abs_diff={diff.max():.2e} max_rel_diff={rel.max():.2e} ok={ok}")
    return ok


def run_all(verbose=False):
    results = {}

    def rnd(*shape):
        return Tensor(np.random.randn(*shape) * 0.5, requires_grad=True)

    # add / broadcast add
    results["add"] = check("add", lambda x: (x + Tensor(np.random.RandomState(1).randn(4, 5))).sum(), rnd(4, 5), verbose=verbose)
    results["add_broadcast"] = check("add_broadcast", lambda x: (x + Tensor(np.random.RandomState(2).randn(1, 5))).sum(), rnd(4, 5), verbose=verbose)

    # sub / neg
    results["sub"] = check("sub", lambda x: (Tensor(np.random.RandomState(3).randn(3, 3)) - x).sum(), rnd(3, 3), verbose=verbose)
    results["neg"] = check("neg", lambda x: (-x).sum(), rnd(3, 3), verbose=verbose)

    # mul / broadcast mul
    results["mul"] = check("mul", lambda x: (x * Tensor(np.random.RandomState(4).randn(4, 5))).sum(), rnd(4, 5), verbose=verbose)
    results["mul_broadcast"] = check("mul_broadcast", lambda x: (x * Tensor(np.random.RandomState(5).randn(5))).sum(), rnd(4, 5), verbose=verbose)

    # div
    other = Tensor(np.random.RandomState(6).randn(4, 5) + 3.0)
    results["div"] = check("div", lambda x: (x / other).sum(), rnd(4, 5), verbose=verbose)

    # pow
    results["pow"] = check("pow", lambda x: ((x * x + 2.0) ** 3).sum(), rnd(3, 3), verbose=verbose)

    # matmul (2D)
    W = Tensor(np.random.RandomState(7).randn(5, 4))
    results["matmul2d"] = check("matmul2d", lambda x: (x.matmul(W)).sum(), rnd(3, 5), verbose=verbose)

    # matmul (batched 3D, e.g. attention QK^T shape)
    Wb = Tensor(np.random.RandomState(8).randn(2, 4, 6))
    results["matmul_batched"] = check("matmul_batched", lambda x: (x.matmul(Wb)).sum(), rnd(2, 3, 4), verbose=verbose)

    # reshape
    results["reshape"] = check("reshape", lambda x: (x.reshape(2, 6) * Tensor(np.random.RandomState(9).randn(2, 6))).sum(), rnd(2, 2, 3), verbose=verbose)

    # permute
    results["permute"] = check("permute", lambda x: (x.permute(0, 2, 1) * Tensor(np.random.RandomState(10).randn(2, 4, 3))).sum(), rnd(2, 3, 4), verbose=verbose)

    # getitem: fancy gather along axis0
    idx = np.array([0, 2, 2, 1])
    results["gather0"] = check("gather0", lambda x: (x[idx]).sum(), rnd(3, 4), verbose=verbose)

    # getitem: slice
    results["slice"] = check("slice", lambda x: (x[1:3, :]).sum(), rnd(4, 4), verbose=verbose)

    # concat
    def concat_fn(x):
        y = Tensor(np.random.RandomState(11).randn(3, 2))
        return Tensor.concat([x, y], axis=1).sum()
    results["concat"] = check("concat", concat_fn, rnd(3, 3), verbose=verbose)

    # sum with axis
    results["sum_axis"] = check("sum_axis", lambda x: (x.sum(axis=1) * Tensor(np.random.RandomState(12).randn(3))).sum(), rnd(3, 4), verbose=verbose)

    # mean
    results["mean"] = check("mean", lambda x: (x.mean(axis=-1) * Tensor(np.random.RandomState(13).randn(3))).sum(), rnd(3, 4), verbose=verbose)

    # exp / log
    results["exp"] = check("exp", lambda x: x.exp().sum(), rnd(3, 3), verbose=verbose)
    results["log"] = check("log", lambda x: (x * x + 1.0).log().sum(), rnd(3, 3), verbose=verbose)

    # tanh / relu / gelu
    results["tanh"] = check("tanh", lambda x: x.tanh().sum(), rnd(3, 3), verbose=verbose)
    results["relu"] = check("relu", lambda x: x.relu().sum(), rnd(3, 3), verbose=verbose)
    results["gelu"] = check("gelu", lambda x: x.gelu().sum(), rnd(3, 3), verbose=verbose)

    # softmax
    results["softmax"] = check("softmax", lambda x: (x.softmax(axis=-1) * Tensor(np.random.RandomState(14).randn(3, 4))).sum(), rnd(3, 4), verbose=verbose)

    # layernorm
    gamma = Tensor(np.random.RandomState(15).randn(5) * 0.1 + 1.0, requires_grad=True)
    beta = Tensor(np.random.RandomState(16).randn(5) * 0.1, requires_grad=True)
    x_ln = Tensor(np.random.RandomState(17).randn(3, 5))
    results["layernorm_x"] = check("layernorm_x", lambda x: x.layernorm(gamma, beta).sum(), rnd(3, 5), verbose=verbose)
    results["layernorm_gamma"] = check("layernorm_gamma", lambda g: x_ln.layernorm(g, beta).sum(), gamma, verbose=verbose)
    results["layernorm_beta"] = check("layernorm_beta", lambda b: x_ln.layernorm(gamma, b).sum(), beta, verbose=verbose)

    return results


if __name__ == "__main__":
    res = run_all(verbose=True)
    n_ok = sum(res.values())
    print(f"\n{n_ok}/{len(res)} ops passed gradient check")
