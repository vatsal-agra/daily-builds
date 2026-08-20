"""A small hand-rolled MLP: explicit forward pass, explicit hand-derived
backprop equations, explicit Adam optimizer step. No autodiff graph —
every layer's gradient is the textbook closed-form chain-rule derivative,
written out directly, and checked against numerical finite differences in
tests/test_nn.py before any agent is trusted to learn with it.

Architecture: Linear -> ReLU -> Linear -> ReLU -> ... -> Linear (linear
output layer; softmax/argmax is applied by the caller as appropriate for
Q-values vs. policy logits).
"""

from __future__ import annotations

import numpy as np


def _he_init(rng, fan_in, fan_out):
    # He (2015) initialization: right variance for a ReLU-gated fan-in.
    std = np.sqrt(2.0 / fan_in)
    return rng.normal(0.0, std, size=(fan_in, fan_out)).astype(np.float64)


class MLP:
    """sizes = [in_dim, hidden1, hidden2, ..., out_dim]."""

    def __init__(self, sizes, seed=None):
        if len(sizes) < 2:
            raise ValueError("need at least an input and output layer")
        self.sizes = list(sizes)
        rng = np.random.default_rng(seed)
        self.Ws = [_he_init(rng, sizes[i], sizes[i + 1]) for i in range(len(sizes) - 1)]
        self.bs = [np.zeros(sizes[i + 1], dtype=np.float64) for i in range(len(sizes) - 1)]

    def params(self):
        """Flat list of (name, array) pairs, in a stable order — used by
        both the Adam optimizer and by weight copy (target networks)."""
        out = []
        for i, W in enumerate(self.Ws):
            out.append((f"W{i}", W))
        for i, b in enumerate(self.bs):
            out.append((f"b{i}", b))
        return out

    def set_params_like(self, other: "MLP"):
        """Hard-copy another MLP's weights into this one (target network sync)."""
        self.Ws = [W.copy() for W in other.Ws]
        self.bs = [b.copy() for b in other.bs]

    def forward(self, x):
        """x: (batch, in_dim) or (in_dim,). Returns (output, cache)."""
        squeeze = x.ndim == 1
        a = np.atleast_2d(x).astype(np.float64)
        zs = []
        activations = [a]
        n_layers = len(self.Ws)
        for i in range(n_layers):
            z = a @ self.Ws[i] + self.bs[i]
            zs.append(z)
            if i < n_layers - 1:
                a = np.maximum(z, 0.0)  # ReLU on hidden layers
            else:
                a = z  # linear output
            activations.append(a)
        out = activations[-1]
        cache = {"zs": zs, "activations": activations}
        return (out[0] if squeeze else out), cache

    def backward(self, cache, d_out):
        """d_out: gradient of the loss w.r.t. the network's output,
        shape (batch, out_dim). Returns grads as {"W0":.., "b0":.., ...},
        averaged over the batch (so the caller's learning rate is
        batch-size independent)."""
        d_out = np.atleast_2d(d_out)
        activations = cache["activations"]
        zs = cache["zs"]
        n_layers = len(self.Ws)
        batch = d_out.shape[0]

        grads = {}
        delta = d_out  # dL/dz for the current layer, starting at the output
        for i in reversed(range(n_layers)):
            a_prev = activations[i]  # input into layer i
            grads[f"W{i}"] = (a_prev.T @ delta) / batch
            grads[f"b{i}"] = delta.mean(axis=0)
            if i > 0:
                d_a_prev = delta @ self.Ws[i].T
                relu_mask = (zs[i - 1] > 0).astype(np.float64)
                delta = d_a_prev * relu_mask
        return grads

    def gradcheck(self, x, d_out, eps=1e-5):
        """Numerical (central finite-difference) gradient of the same
        scalar loss mean(out * d_out) w.r.t. every parameter, for testing
        the analytic backward() above against ground truth. Divides by
        batch size to match backward()'s own averaging convention
        (grads[f"W{i}"] = (a_prev.T @ delta) / batch) — every real caller
        (DQN's TD loss, REINFORCE's policy/value loss) relies on that
        batch-size-independent averaging, so the check has to use the
        same convention or it's checking the wrong thing."""
        out, cache = self.forward(x)
        batch = np.atleast_2d(x).shape[0]

        def loss():
            o, _ = self.forward(x)
            return float(np.sum(o * d_out)) / batch

        analytic = self.backward(cache, d_out)
        numeric = {}
        for name, arr in self.params():
            g = np.zeros_like(arr)
            it = np.nditer(arr, flags=["multi_index"])
            for _ in it:
                idx = it.multi_index
                orig = arr[idx]
                arr[idx] = orig + eps
                lp = loss()
                arr[idx] = orig - eps
                lm = loss()
                arr[idx] = orig
                g[idx] = (lp - lm) / (2 * eps)
            numeric[name] = g
        return analytic, numeric


class Adam:
    """Adam optimizer (Kingma & Ba 2014) operating directly on an MLP's
    parameter arrays in place."""

    def __init__(self, mlp: MLP, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.mlp = mlp
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.t = 0
        self.m = {name: np.zeros_like(arr) for name, arr in mlp.params()}
        self.v = {name: np.zeros_like(arr) for name, arr in mlp.params()}

    def step(self, grads):
        self.t += 1
        params = dict(self.mlp.params())
        for name, g in grads.items():
            self.m[name] = self.beta1 * self.m[name] + (1 - self.beta1) * g
            self.v[name] = self.beta2 * self.v[name] + (1 - self.beta2) * (g * g)
            m_hat = self.m[name] / (1 - self.beta1**self.t)
            v_hat = self.v[name] / (1 - self.beta2**self.t)
            params[name] -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
        # params[name] arrays are the *same objects* stored in mlp.Ws/mlp.bs
        # (numpy in-place -=), so no writeback step is needed.


def softmax(logits, axis=-1):
    z = logits - np.max(logits, axis=axis, keepdims=True)
    ez = np.exp(z)
    return ez / np.sum(ez, axis=axis, keepdims=True)
