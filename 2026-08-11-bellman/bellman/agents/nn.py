"""A small, purpose-built neural network: hand-derived forward and
backward passes, no autodiff.

This is deliberately *not* a reuse of Cotangent's (2026-06-16) generic
scalar-autodiff engine. Cotangent builds a computation graph and
backpropagates through arbitrary Python expressions. Bellman only ever
needs one fixed shape -- a small MLP mapping a state vector to either
Q-values (one per action) or policy logits -- so every gradient here is
derived once, directly, for exactly that shape (dense layer -> ReLU ->
dense layer), verified against central-difference numerical gradients in
tests/test_nn.py, and kept plain-list/no-numpy for consistency with the
rest of the repo's pure-Python builds.
"""
import math
import random


def _zeros(rows, cols):
    return [[0.0 for _ in range(cols)] for _ in range(rows)]


class Dense:
    """y = activation(W @ x + b). W is n_out x n_in, x and b are n_in/n_out
    vectors (plain lists). activation is 'relu' or 'linear'."""

    def __init__(self, n_in, n_out, activation="relu", rng=None):
        rng = rng or random.Random()
        if activation == "relu":
            scale = math.sqrt(2.0 / n_in)
        else:
            scale = math.sqrt(1.0 / n_in)
        self.n_in, self.n_out = n_in, n_out
        self.activation = activation
        self.W = [[rng.gauss(0.0, scale) for _ in range(n_in)] for _ in range(n_out)]
        self.b = [0.0 for _ in range(n_out)]
        self._x = None
        self._z = None

    def forward(self, x):
        z = [sum(self.W[o][i] * x[i] for i in range(self.n_in)) + self.b[o]
             for o in range(self.n_out)]
        if self.activation == "relu":
            a = [v if v > 0.0 else 0.0 for v in z]
        else:
            a = z
        self._x, self._z = x, z
        return a

    def backward(self, d_out):
        """d_out: gradient of the loss wrt this layer's *output* (post
        activation). Returns (d_in, dW, db)."""
        if self.activation == "relu":
            d_z = [d_out[o] if self._z[o] > 0.0 else 0.0 for o in range(self.n_out)]
        else:
            d_z = d_out
        dW = _zeros(self.n_out, self.n_in)
        db = [0.0] * self.n_out
        d_in = [0.0] * self.n_in
        for o in range(self.n_out):
            dzo = d_z[o]
            db[o] = dzo
            Wo = self.W[o]
            for i in range(self.n_in):
                dW[o][i] = dzo * self._x[i]
                d_in[i] += dzo * Wo[i]
        return d_in, dW, db

    def params(self):
        return [("W", self.W), ("b", self.b)]


class MLP:
    """A stack of Dense layers: linear -> relu -> ... -> linear (last
    layer has no activation, since outputs here are always Q-values or
    unnormalized policy logits, not probabilities)."""

    def __init__(self, sizes, seed=0):
        rng = random.Random(seed)
        self.layers = []
        for i in range(len(sizes) - 1):
            is_last = i == len(sizes) - 2
            act = "linear" if is_last else "relu"
            self.layers.append(Dense(sizes[i], sizes[i + 1], activation=act, rng=rng))

    def forward(self, x):
        a = x
        for layer in self.layers:
            a = layer.forward(a)
        return a

    def backward(self, d_out):
        """Returns list of (dW, db) per layer, in layer order."""
        grads = []
        d = d_out
        for layer in reversed(self.layers):
            d, dW, db = layer.backward(d)
            grads.append((dW, db))
        grads.reverse()
        return grads

    def parameters(self):
        return self.layers

    def clone(self):
        """Deep copy, used to build DQN's target network."""
        import copy

        other = MLP.__new__(MLP)
        other.layers = copy.deepcopy(self.layers)
        return other

    def load_from(self, other):
        """Hard-copy parameters from another MLP of identical shape --
        used to periodically sync DQN's target network."""
        for mine, theirs in zip(self.layers, other.layers):
            mine.W = [row[:] for row in theirs.W]
            mine.b = theirs.b[:]


class Adam:
    """Standard Adam (Kingma & Ba 2014), applied per-parameter-tensor."""

    def __init__(self, mlp, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.lr, self.beta1, self.beta2, self.eps = lr, beta1, beta2, eps
        self.t = 0
        self.m = []
        self.v = []
        for layer in mlp.layers:
            mW = _zeros(layer.n_out, layer.n_in)
            vW = _zeros(layer.n_out, layer.n_in)
            mb = [0.0] * layer.n_out
            vb = [0.0] * layer.n_out
            self.m.append((mW, mb))
            self.v.append((vW, vb))

    def step(self, mlp, grads):
        self.t += 1
        b1, b2, eps, lr = self.beta1, self.beta2, self.eps, self.lr
        bias1 = 1.0 - b1 ** self.t
        bias2 = 1.0 - b2 ** self.t
        for li, (layer, (dW, db)) in enumerate(zip(mlp.layers, grads)):
            mW, mb = self.m[li]
            vW, vb = self.v[li]
            for o in range(layer.n_out):
                for i in range(layer.n_in):
                    g = dW[o][i]
                    mW[o][i] = b1 * mW[o][i] + (1 - b1) * g
                    vW[o][i] = b2 * vW[o][i] + (1 - b2) * g * g
                    mhat = mW[o][i] / bias1
                    vhat = vW[o][i] / bias2
                    layer.W[o][i] -= lr * mhat / (math.sqrt(vhat) + eps)
                gb = db[o]
                mb[o] = b1 * mb[o] + (1 - b1) * gb
                vb[o] = b2 * vb[o] + (1 - b2) * gb * gb
                mhatb = mb[o] / bias1
                vhatb = vb[o] / bias2
                layer.b[o] -= lr * mhatb / (math.sqrt(vhatb) + eps)
