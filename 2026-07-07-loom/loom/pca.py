"""2D PCA via power iteration + deflation - no np.linalg.eig/svd call.

This is "from scratch" in the same spirit as the rest of Loom: NumPy
supplies matmul/norm, but the eigen-decomposition algorithm itself
(power iteration with deflation) is ours.
"""
import numpy as np


def pca_2d(X, n_iters=200, seed=0):
    """X: (N, D) array. Returns (N, 2) projection onto the top-2 principal
    components (by variance)."""
    rng = np.random.default_rng(seed)
    X = X - X.mean(axis=0, keepdims=True)
    cov = (X.T @ X) / X.shape[0]

    A = cov.copy()
    components = []
    for _ in range(2):
        v = rng.normal(size=A.shape[0])
        v /= np.linalg.norm(v) + 1e-12
        for _ in range(n_iters):
            v = A @ v
            norm = np.linalg.norm(v)
            if norm < 1e-12:
                break
            v /= norm
        eigval = float(v @ A @ v)
        components.append(v)
        A = A - eigval * np.outer(v, v)  # deflate so the next iteration finds the 2nd component

    W = np.stack(components, axis=1)  # (D, 2)
    return X @ W
