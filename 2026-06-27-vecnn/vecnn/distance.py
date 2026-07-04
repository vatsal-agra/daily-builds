"""
Distance / similarity metrics for vector search.

All functions take numpy arrays and return a scalar float where
LOWER is CLOSER (so every metric is a "distance" even for inner
product, which is negated).

Supported metrics:
  "cosine"     — 1 - cosine_similarity  ∈ [0, 2]
  "euclidean"  — L2 distance            ∈ [0, ∞)
  "inner"      — negative dot product   ∈ (-∞, ∞)
"""
import numpy as np


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 1.0  # orthogonal by convention
    return float(1.0 - np.dot(a, b) / (na * nb))


def euclidean_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = a - b
    return float(np.sqrt(np.dot(diff, diff)))


def inner_product_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(-np.dot(a, b))


# Vectorised variants: compute distance from one query to many candidates.
# Returns a 1-D array of distances aligned with the rows of `matrix`.

def cosine_distance_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query: (d,)  matrix: (n, d) → distances (n,)"""
    nq = np.linalg.norm(query)
    nm = np.linalg.norm(matrix, axis=1)
    dots = matrix @ query
    denom = nm * nq
    # avoid division by zero
    safe = denom != 0
    result = np.ones(len(matrix), dtype=np.float64)
    result[safe] = 1.0 - dots[safe] / denom[safe]
    return result


def euclidean_distance_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    diff = matrix - query
    return np.sqrt((diff * diff).sum(axis=1))


def inner_product_distance_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return -(matrix @ query)


# Registry used by the rest of the code.
METRICS = {
    "cosine": cosine_distance,
    "euclidean": euclidean_distance,
    "inner": inner_product_distance,
}

BATCH_METRICS = {
    "cosine": cosine_distance_batch,
    "euclidean": euclidean_distance_batch,
    "inner": inner_product_distance_batch,
}

VALID_METRICS = set(METRICS.keys())


def get_metric(name: str):
    if name not in METRICS:
        raise ValueError(f"Unknown metric '{name}'. Choose from: {sorted(VALID_METRICS)}")
    return METRICS[name]


def get_batch_metric(name: str):
    return BATCH_METRICS[name]
