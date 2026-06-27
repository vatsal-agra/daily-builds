"""Tests for distance metrics."""
import math
import unittest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vecnn.distance import (
    cosine_distance, euclidean_distance, inner_product_distance,
    cosine_distance_batch, euclidean_distance_batch, inner_product_distance_batch,
    get_metric, get_batch_metric,
)


class TestCosineDistance(unittest.TestCase):

    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        self.assertAlmostEqual(cosine_distance(a, a), 0.0, places=10)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        self.assertAlmostEqual(cosine_distance(a, b), 1.0, places=10)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        self.assertAlmostEqual(cosine_distance(a, b), 2.0, places=10)

    def test_zero_vector_returns_one(self):
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])
        self.assertEqual(cosine_distance(a, b), 1.0)

    def test_symmetry(self):
        rng = np.random.default_rng(1)
        for _ in range(20):
            a, b = rng.standard_normal(32), rng.standard_normal(32)
            self.assertAlmostEqual(cosine_distance(a, b), cosine_distance(b, a), places=12)

    def test_range(self):
        rng = np.random.default_rng(2)
        for _ in range(50):
            a, b = rng.standard_normal(16), rng.standard_normal(16)
            d = cosine_distance(a, b)
            self.assertGreaterEqual(d, -1e-12)
            self.assertLessEqual(d, 2.0 + 1e-12)

    def test_batch_matches_scalar(self):
        rng = np.random.default_rng(3)
        q = rng.standard_normal(8)
        mat = rng.standard_normal((20, 8))
        batch = cosine_distance_batch(q, mat)
        for i in range(len(mat)):
            self.assertAlmostEqual(batch[i], cosine_distance(q, mat[i]), places=10)


class TestEuclideanDistance(unittest.TestCase):

    def test_zero(self):
        a = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(euclidean_distance(a, a), 0.0, places=10)

    def test_known_value(self):
        a = np.array([0.0, 0.0])
        b = np.array([3.0, 4.0])
        self.assertAlmostEqual(euclidean_distance(a, b), 5.0, places=10)

    def test_symmetry(self):
        rng = np.random.default_rng(4)
        for _ in range(20):
            a, b = rng.standard_normal(16), rng.standard_normal(16)
            self.assertAlmostEqual(euclidean_distance(a, b), euclidean_distance(b, a), places=12)

    def test_triangle_inequality(self):
        rng = np.random.default_rng(5)
        for _ in range(30):
            a, b, c = [rng.standard_normal(8) for _ in range(3)]
            d_ab = euclidean_distance(a, b)
            d_bc = euclidean_distance(b, c)
            d_ac = euclidean_distance(a, c)
            self.assertLessEqual(d_ac, d_ab + d_bc + 1e-10)

    def test_batch_matches_scalar(self):
        rng = np.random.default_rng(6)
        q = rng.standard_normal(8)
        mat = rng.standard_normal((20, 8))
        batch = euclidean_distance_batch(q, mat)
        for i in range(len(mat)):
            self.assertAlmostEqual(batch[i], euclidean_distance(q, mat[i]), places=10)


class TestInnerProductDistance(unittest.TestCase):

    def test_known(self):
        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        # -dot(a,b) = -(3+8) = -11
        self.assertAlmostEqual(inner_product_distance(a, b), -11.0, places=10)

    def test_batch(self):
        rng = np.random.default_rng(7)
        q = rng.standard_normal(8)
        mat = rng.standard_normal((15, 8))
        batch = inner_product_distance_batch(q, mat)
        for i in range(len(mat)):
            self.assertAlmostEqual(batch[i], inner_product_distance(q, mat[i]), places=10)


class TestRegistry(unittest.TestCase):

    def test_get_metric_valid(self):
        for name in ["cosine", "euclidean", "inner"]:
            fn = get_metric(name)
            self.callable(fn)

    def callable(self, fn):
        a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
        fn(a, b)  # must not raise

    def test_get_metric_invalid(self):
        with self.assertRaises(ValueError):
            get_metric("manhattan")

    def test_get_batch_metric(self):
        for name in ["cosine", "euclidean", "inner"]:
            fn = get_batch_metric(name)
            q = np.array([1.0, 0.0, 0.0])
            mat = np.eye(3)
            result = fn(q, mat)
            self.assertEqual(result.shape, (3,))


if __name__ == "__main__":
    unittest.main()
