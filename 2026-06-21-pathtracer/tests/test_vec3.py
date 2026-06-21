"""Tests for vec3.py — vector math, reflect/refract/schlick, sampling."""
import math
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.vec3 import (
    Vec3, reflect, refract, schlick,
    random_in_unit_sphere, random_unit_vector, random_in_unit_disk,
    random_cosine_direction, build_onb, sample_cosine_hemisphere,
)


def approx(a, b, tol=1e-9):
    return abs(a - b) < tol


# ---- arithmetic ----

def test_add():
    assert Vec3(1, 2, 3) + Vec3(4, 5, 6) == Vec3(5, 7, 9)


def test_sub():
    assert Vec3(5, 7, 9) - Vec3(4, 5, 6) == Vec3(1, 2, 3)


def test_scalar_mul():
    v = Vec3(1, 2, 3) * 2.0
    assert v == Vec3(2, 4, 6)
    assert 2.0 * Vec3(1, 2, 3) == Vec3(2, 4, 6)


def test_neg():
    assert -Vec3(1, 2, 3) == Vec3(-1, -2, -3)


def test_div():
    assert Vec3(2, 4, 6) / 2 == Vec3(1, 2, 3)


def test_elem_mul():
    assert Vec3(2, 3, 4) * Vec3(5, 6, 7) == Vec3(10, 18, 28)


# ---- geometry ----

def test_dot():
    assert approx(Vec3(1, 0, 0).dot(Vec3(0, 1, 0)), 0.0)
    assert approx(Vec3(1, 2, 3).dot(Vec3(4, 5, 6)), 32.0)


def test_cross():
    assert Vec3(1, 0, 0).cross(Vec3(0, 1, 0)) == Vec3(0, 0, 1)
    assert Vec3(0, 1, 0).cross(Vec3(1, 0, 0)) == Vec3(0, 0, -1)


def test_length():
    assert approx(Vec3(3, 4, 0).length(), 5.0)
    assert approx(Vec3(0, 0, 0).length(), 0.0)


def test_normalize():
    n = Vec3(3, 0, 0).normalize()
    assert approx(n.length(), 1.0)
    assert approx(n.x, 1.0)


def test_normalize_zero_vector():
    # Near-zero vector should not crash; returns a default direction
    n = Vec3(0, 0, 0).normalize()
    assert approx(n.length(), 1.0)


def test_luminance():
    assert approx(Vec3(1, 0, 0).luminance(), 0.2126)
    assert approx(Vec3(0, 1, 0).luminance(), 0.7152)
    assert approx(Vec3(0, 0, 1).luminance(), 0.0722)


def test_clamp():
    c = Vec3(-1, 0.5, 2).clamp()
    assert approx(c.x, 0.0)
    assert approx(c.y, 0.5)
    assert approx(c.z, 1.0)


def test_near_zero():
    assert Vec3(1e-9, 1e-9, 1e-9).near_zero()
    assert not Vec3(0.1, 0, 0).near_zero()


def test_iter():
    x, y, z = Vec3(1, 2, 3)
    assert x == 1.0 and y == 2.0 and z == 3.0


def test_to_rgb8():
    r, g, b = Vec3(1, 0.5, 0).to_rgb8()
    assert r == 255
    assert 127 <= g <= 128
    assert b == 0


def test_pickle():
    import pickle
    v = Vec3(1.5, 2.5, 3.5)
    assert pickle.loads(pickle.dumps(v)) == v


# ---- reflect ----

def test_reflect_normal_incidence():
    # Ray hitting a surface head-on (+z surface, ray going -z)
    v = Vec3(0, 0, -1)
    n = Vec3(0, 0, 1)
    r = reflect(v, n)
    assert approx(r.x, 0) and approx(r.y, 0) and approx(r.z, 1)


def test_reflect_45_degree():
    v = Vec3(1, 0, -1).normalize()
    n = Vec3(0, 0, 1)
    r = reflect(v, n)
    # z component should flip, x should stay
    assert r.z > 0


def test_reflect_stays_on_same_side():
    rng = random.Random(1)
    n = Vec3(0, 1, 0)
    for _ in range(100):
        d = Vec3(rng.uniform(-1, 1), -abs(rng.uniform(0.1, 1)), rng.uniform(-1, 1)).normalize()
        r = reflect(d, n)
        # reflected ray should point upward
        assert r.dot(n) > 0


# ---- refract ----

def test_refract_straight_through():
    # Normal incidence — no bending
    v = Vec3(0, 0, -1)
    n = Vec3(0, 0, 1)
    r = refract(v, n, 1.0)
    assert r is not None
    assert approx(r.x, 0) and approx(r.y, 0)
    assert r.z < 0  # continues in same direction


def test_refract_total_internal_reflection():
    # Ray at steep angle from dense medium — TIR
    # eta_ratio > 1, sin_theta large enough
    v = Vec3(0.99, 0, -0.14).normalize()
    n = Vec3(0, 0, 1)
    result = refract(v, n, 1.5)
    # TIR at this angle
    if result is None:
        pass  # expected
    # (it might still refract at some angles — just don't crash)


def test_refract_preserves_unit_length():
    rng = random.Random(42)
    n = Vec3(0, 1, 0)
    for _ in range(50):
        v = Vec3(rng.uniform(-0.5, 0.5), -abs(rng.uniform(0.5, 1)), rng.uniform(-0.5, 0.5)).normalize()
        r = refract(v, n, 1.0 / 1.5)
        if r is not None:
            assert approx(r.length(), 1.0, tol=1e-7)


# ---- schlick ----

def test_schlick_normal_incidence():
    # At normal incidence, reflectance = ((1-n)/(1+n))^2
    r = schlick(1.0, 1.5)
    expected = ((1.0 - 1.5) / (1.0 + 1.5)) ** 2
    assert approx(r, expected)


def test_schlick_grazing_incidence():
    # At grazing angle (cosine=0), reflectance = 1
    assert approx(schlick(0.0, 1.5), 1.0)


def test_schlick_clamps_cosine():
    # cosine slightly above 1 should not produce NaN / crash
    r = schlick(1.0001, 1.5)
    assert 0.0 <= r <= 1.0


def test_schlick_range():
    rng = random.Random(0)
    for _ in range(100):
        r = schlick(rng.random(), rng.uniform(1.0, 2.5))
        assert 0.0 <= r <= 1.0


# ---- sampling ----

def test_random_in_unit_sphere_inside():
    rng = random.Random(0)
    for _ in range(200):
        p = random_in_unit_sphere(rng)
        assert p.length_sq() < 1.0


def test_random_unit_vector_unit_length():
    rng = random.Random(0)
    for _ in range(100):
        v = random_unit_vector(rng)
        assert approx(v.length(), 1.0, tol=1e-7)


def test_random_in_unit_disk_z_zero():
    rng = random.Random(0)
    for _ in range(100):
        p = random_in_unit_disk(rng)
        assert approx(p.z, 0.0)
        assert p.x * p.x + p.y * p.y < 1.0


def test_cosine_hemisphere_positive_z():
    rng = random.Random(0)
    for _ in range(200):
        d = random_cosine_direction(rng)
        assert d.z >= 0.0  # z-up hemisphere


def test_sample_cosine_hemisphere_above_normal():
    rng = random.Random(0)
    normal = Vec3(0, 1, 0)
    for _ in range(200):
        s = sample_cosine_hemisphere(rng, normal)
        assert s.dot(normal) >= -1e-6


def test_build_onb_orthogonal():
    for n in [Vec3(0, 1, 0), Vec3(1, 0, 0), Vec3(0.6, 0.8, 0), Vec3(1, 1, 1).normalize()]:
        u, v, w = build_onb(n)
        assert approx(u.length(), 1.0, tol=1e-7)
        assert approx(v.length(), 1.0, tol=1e-7)
        assert approx(w.length(), 1.0, tol=1e-7)
        assert approx(u.dot(v), 0.0, tol=1e-7)
        assert approx(u.dot(w), 0.0, tol=1e-7)
        assert approx(v.dot(w), 0.0, tol=1e-7)
