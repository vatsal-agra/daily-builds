"""Tests for materials.py — scatter directions, energy conservation."""
import random
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.vec3 import Vec3
from pathtracer.ray import Ray
from pathtracer.shapes import HitRecord, Sphere
from pathtracer.materials import Lambertian, Metal, Dielectric, DiffuseLight


def _make_hit(normal=None, p=None, front_face=True, ray_dir=None):
    """Synthetic HitRecord for testing scatter."""
    if normal is None:
        normal = Vec3(0, 1, 0)
    if p is None:
        p = Vec3(0, 0, 0)
    if ray_dir is None:
        ray_dir = Vec3(0, -1, 0) if front_face else Vec3(0, 1, 0)
    mat = Lambertian(Vec3(0.5, 0.5, 0.5))
    return HitRecord(1.0, p, normal, ray_dir, 0.5, 0.5, mat)


# ---- Lambertian ----

def test_lambertian_scatter_returns_ray():
    mat = Lambertian(Vec3(0.8, 0.4, 0.2))
    rng = random.Random(0)
    hit = _make_hit()
    result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), hit, rng)
    assert result is not None
    ray, att = result
    assert att.x > 0 or att.y > 0 or att.z > 0


def test_lambertian_scatter_above_surface():
    mat = Lambertian(Vec3(0.5, 0.5, 0.5))
    rng = random.Random(1)
    normal = Vec3(0, 1, 0)
    hit = _make_hit(normal=normal)
    for _ in range(100):
        result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), hit, rng)
        assert result is not None
        scattered_ray, _ = result
        # Scattered direction should be above the surface (positive y)
        assert scattered_ray.direction.dot(normal) >= -1e-6


def test_lambertian_attenuation_matches_albedo():
    color = Vec3(0.3, 0.6, 0.9)
    mat = Lambertian(color)
    rng = random.Random(2)
    hit = _make_hit()
    result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), hit, rng)
    assert result is not None
    _, att = result
    assert abs(att.x - color.x) < 1e-9
    assert abs(att.y - color.y) < 1e-9
    assert abs(att.z - color.z) < 1e-9


def test_lambertian_emitted_zero():
    mat = Lambertian(Vec3(0.5, 0.5, 0.5))
    e = mat.emitted(0, 0, Vec3(0, 0, 0))
    assert e.x == 0 and e.y == 0 and e.z == 0


# ---- Metal ----

def test_metal_scatter_direction_reflects():
    mat = Metal(Vec3(0.9, 0.9, 0.9), roughness=0.0)
    rng = random.Random(0)
    normal = Vec3(0, 1, 0)
    ray_in = Ray(Vec3(0, 1, 0), Vec3(0.5, -1, 0).normalize())
    hit = _make_hit(normal=normal, ray_dir=ray_in.direction)
    result = mat.scatter(ray_in, hit, rng)
    assert result is not None
    scattered, att = result
    # Reflected ray should be above surface
    assert scattered.direction.dot(normal) > 0


def test_metal_perfect_mirror():
    mat = Metal(Vec3(1, 1, 1), roughness=0.0)
    rng = random.Random(0)
    normal = Vec3(0, 1, 0)
    d_in = Vec3(1, -1, 0).normalize()
    ray_in = Ray(Vec3(-1, 1, 0), d_in)
    hit = _make_hit(normal=normal, ray_dir=d_in)
    result = mat.scatter(ray_in, hit, rng)
    assert result is not None
    scattered, _ = result
    # Perfect mirror: x component preserved, y flips
    assert abs(scattered.direction.x - d_in.x) < 0.01
    assert scattered.direction.y > 0


def test_metal_roughness_scatter_above():
    mat = Metal(Vec3(0.8, 0.8, 0.8), roughness=0.3)
    rng = random.Random(3)
    normal = Vec3(0, 1, 0)
    absorbed = 0
    for _ in range(200):
        d_in = Vec3(0.2, -1, 0.2).normalize()
        ray_in = Ray(Vec3(0, 1, 0), d_in)
        hit = _make_hit(normal=normal, ray_dir=d_in)
        result = mat.scatter(ray_in, hit, rng)
        if result is None:
            absorbed += 1
        else:
            scattered, _ = result
            # If scattered, must be above surface
            assert scattered.direction.dot(normal) > 0
    # Some absorption is ok with roughness, but most should scatter
    assert absorbed < 100


def test_metal_normalized_scatter_direction():
    mat = Metal(Vec3(0.7, 0.7, 0.7), roughness=0.5)
    rng = random.Random(4)
    normal = Vec3(0, 1, 0)
    for _ in range(50):
        d_in = Vec3(0.1, -1, 0.1).normalize()
        ray_in = Ray(Vec3(0, 2, 0), d_in)
        hit = _make_hit(normal=normal, ray_dir=d_in)
        result = mat.scatter(ray_in, hit, rng)
        if result is not None:
            scattered, _ = result
            assert abs(scattered.direction.length() - 1.0) < 1e-6


# ---- Dielectric ----

def test_dielectric_scatter_not_none():
    mat = Dielectric(1.5)
    rng = random.Random(0)
    normal = Vec3(0, 1, 0)
    d_in = Vec3(0, -1, 0)
    hit = _make_hit(normal=normal, ray_dir=d_in)
    result = mat.scatter(Ray(Vec3(0, 1, 0), d_in), hit, rng)
    assert result is not None


def test_dielectric_attenuation_is_white():
    mat = Dielectric(1.5)
    rng = random.Random(0)
    hit = _make_hit()
    result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), hit, rng)
    assert result is not None
    _, att = result
    assert abs(att.x - 1.0) < 1e-9
    assert abs(att.y - 1.0) < 1e-9
    assert abs(att.z - 1.0) < 1e-9


def test_dielectric_emitted_zero():
    mat = Dielectric(1.5)
    assert mat.emitted(0, 0, Vec3(0, 0, 0)) == Vec3(0, 0, 0)


def test_dielectric_hollow_glass_back_face():
    # Inner sphere (negative radius) — ray exits glass.
    # hit.front_face = False, so eta_ratio = ior = 1.5 (not 1/1.5)
    mat = Dielectric(1.5)
    rng = random.Random(0)
    # Simulate a ray inside glass heading outward
    # front_face=False means ray is inside the material
    normal = Vec3(0, 1, 0)  # outward normal (pointing toward camera)
    d_in = Vec3(0, 1, 0)    # ray going upward (same direction as outward normal)
    hit = _make_hit(normal=normal, front_face=False, ray_dir=d_in)
    result = mat.scatter(Ray(Vec3(0, -1, 0), d_in), hit, rng)
    assert result is not None


# ---- DiffuseLight ----

def test_diffuse_light_no_scatter():
    mat = DiffuseLight(Vec3(1, 1, 1), intensity=2.0)
    rng = random.Random(0)
    hit = _make_hit()
    result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), hit, rng)
    assert result is None


def test_diffuse_light_emitted():
    mat = DiffuseLight(Vec3(1, 0.5, 0.2), intensity=3.0)
    e = mat.emitted(0, 0, Vec3(0, 0, 0))
    # color * intensity = (3, 1.5, 0.6)
    assert abs(e.x - 3.0) < 1e-9
    assert abs(e.y - 1.5) < 1e-9
    assert abs(e.z - 0.6) < 1e-9


# ---- Energy conservation check ----

def test_lambertian_energy_conservation():
    # Average luminance of attenuation * scattered should be ≤ incident
    mat = Lambertian(Vec3(0.9, 0.9, 0.9))  # near-white, worst case
    rng = random.Random(5)
    normal = Vec3(0, 1, 0)
    attenuations = []
    for _ in range(500):
        d_in = Vec3(rng.uniform(-0.5, 0.5), -1, rng.uniform(-0.5, 0.5)).normalize()
        hit = _make_hit(normal=normal, ray_dir=d_in)
        result = mat.scatter(Ray(Vec3(0, 1, 0), d_in), hit, rng)
        if result is not None:
            _, att = result
            attenuations.append(att.luminance())
    avg = sum(attenuations) / len(attenuations)
    # Average attenuation ≤ albedo luminance (cosine weighting reduces it)
    assert avg <= 0.9 + 1e-6
