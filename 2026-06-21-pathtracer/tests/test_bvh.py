"""Tests for bvh.py — BVH correctness vs brute-force, edge cases."""
import random
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.vec3 import Vec3
from pathtracer.ray import Ray
from pathtracer.materials import Lambertian
from pathtracer.shapes import Sphere, HittableList
from pathtracer.bvh import build_bvh


MAT = Lambertian(Vec3(0.5, 0.5, 0.5))


def _make_spheres(n, seed=0):
    rng = random.Random(seed)
    return [
        Sphere(Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)),
               rng.uniform(0.1, 0.3), MAT)
        for _ in range(n)
    ]


def _ray_towards(target, origin=Vec3(0, 0, 10)):
    d = (target - origin).normalize()
    return Ray(origin, d)


# ---- correctness: BVH vs HittableList ----

def test_bvh_matches_brute_force_hits():
    objects = _make_spheres(30, seed=1)
    bvh = build_bvh(list(objects))
    brute = HittableList(list(objects))

    rng = random.Random(2)
    mismatches = 0
    for _ in range(200):
        d = Vec3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)).normalize()
        r = Ray(Vec3(0, 0, 20), d)
        h_bvh = bvh.hit(r, 1e-4, 1e10)
        h_brute = brute.hit(r, 1e-4, 1e10)
        if (h_bvh is None) != (h_brute is None):
            mismatches += 1
        elif h_bvh is not None and abs(h_bvh.t - h_brute.t) > 1e-6:
            mismatches += 1
    assert mismatches == 0, f"{mismatches} mismatches between BVH and brute force"


def test_bvh_t_values_match():
    objects = _make_spheres(20, seed=3)
    bvh = build_bvh(list(objects))
    brute = HittableList(list(objects))

    rng = random.Random(4)
    for _ in range(100):
        d = Vec3(rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), -1).normalize()
        r = Ray(Vec3(0, 0, 10), d)
        h_bvh = bvh.hit(r, 1e-4, 1e10)
        h_brute = brute.hit(r, 1e-4, 1e10)
        if h_brute is not None:
            assert h_bvh is not None
            assert abs(h_bvh.t - h_brute.t) < 1e-5


# ---- edge cases ----

def test_build_bvh_empty():
    result = build_bvh([])
    # Should not crash; returns a HittableList
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    assert result.hit(r, 1e-4, 1e10) is None


def test_build_bvh_single():
    s = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    bvh = build_bvh([s])
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = bvh.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 0.5) < 1e-6


def test_build_bvh_two():
    s1 = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    s2 = Sphere(Vec3(0, 0, -3), 0.5, MAT)
    bvh = build_bvh([s1, s2])
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = bvh.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 0.5) < 1e-6


def test_bvh_large_scene_no_misses():
    # 100 spheres laid out in a grid — deterministic rays should all hit
    objects = []
    for i in range(10):
        for j in range(10):
            c = Vec3(i - 4.5, j - 4.5, -5)
            objects.append(Sphere(c, 0.4, MAT))
    bvh = build_bvh(list(objects))
    brute = HittableList(list(objects))

    mismatches = 0
    for i in range(10):
        for j in range(10):
            target = Vec3(i - 4.5, j - 4.5, -5)
            r = _ray_towards(target, Vec3(i - 4.5, j - 4.5, 10))
            h_bvh = bvh.hit(r, 1e-4, 1e10)
            h_brute = brute.hit(r, 1e-4, 1e10)
            if (h_bvh is None) != (h_brute is None):
                mismatches += 1
    assert mismatches == 0


def test_bvh_degenerate_coplanar():
    # All spheres on the same plane — SAH may degenerate but should not crash
    objects = [Sphere(Vec3(i * 0.5, 0, -1), 0.2, MAT) for i in range(10)]
    bvh = build_bvh(list(objects))
    brute = HittableList(list(objects))
    r = Ray(Vec3(2.0, 0, 0), Vec3(0, 0, -1))
    h_bvh = bvh.hit(r, 1e-4, 1e10)
    h_brute = brute.hit(r, 1e-4, 1e10)
    # Both should agree
    assert (h_bvh is None) == (h_brute is None)
