"""Tests for shapes.py — hit/miss for all primitives, edge cases."""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.vec3 import Vec3
from pathtracer.ray import Ray
from pathtracer.materials import Lambertian
from pathtracer.shapes import Sphere, Box, Plane, Triangle, HittableList, AABB


MAT = Lambertian(Vec3(0.5, 0.5, 0.5))


# ---- Sphere ----

def test_sphere_hit_front():
    s = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = s.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 0.5) < 1e-6
    assert hit.front_face is True


def test_sphere_hit_back_face():
    # Ray from inside the sphere
    s = Sphere(Vec3(0, 0, 0), 1.0, MAT)
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = s.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert hit.front_face is False  # hitting inside surface


def test_sphere_miss():
    s = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    r = Ray(Vec3(0, 2, 0), Vec3(0, 0, -1))  # ray misses sphere
    assert s.hit(r, 1e-4, 1e10) is None


def test_sphere_t_min_max():
    s = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    # Sphere occupies t in [0.5, 1.5]. t_min=2.0 excludes both roots.
    assert s.hit(r, 2.0, 1e10) is None
    # t_max=0.4 also excludes both roots
    assert s.hit(r, 1e-4, 0.4) is None
    # t_min=0.6 excludes near root (t=0.5) but far root (t=1.5) is still in range
    far_hit = s.hit(r, 0.6, 1e10)
    assert far_hit is not None
    assert abs(far_hit.t - 1.5) < 1e-6


def test_sphere_negative_radius_normal():
    # Negative radius (hollow-glass inner sphere): normal should point outward from center
    s = Sphere(Vec3(0, 0, 0), -1.0, MAT)
    r = Ray(Vec3(0, 0, 2), Vec3(0, 0, -1))
    hit = s.hit(r, 1e-4, 1e10)
    assert hit is not None
    # Outward normal computed with abs(radius) — should point AWAY from center
    # hit.p is at (0,0,1), outward_normal should be (0,0,1)
    assert hit.normal.z > 0


def test_sphere_normal_unit_length():
    s = Sphere(Vec3(3, 1, -2), 0.7, MAT)
    r = Ray(Vec3(0, 0, 0), Vec3(3, 1, -2).normalize())
    hit = s.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.normal.length() - 1.0) < 1e-6


def test_sphere_uv_range():
    import random
    rng = random.Random(0)
    s = Sphere(Vec3(0, 0, 0), 1.0, MAT)
    for _ in range(50):
        d = Vec3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)).normalize()
        r = Ray(Vec3(0, 0, 0) - d * 2, d)
        hit = s.hit(r, 1e-4, 1e10)
        if hit is not None:
            assert 0.0 <= hit.u <= 1.0
            assert 0.0 <= hit.v <= 1.0


def test_sphere_bounding_box():
    s = Sphere(Vec3(1, 2, 3), 0.5, MAT)
    bb = s.bounding_box()
    assert bb.mn.x == 0.5
    assert bb.mx.y == 2.5


# ---- Box ----

def test_box_hit_front():
    b = Box(Vec3(-1, -1, -1), Vec3(1, 1, 1), MAT)
    r = Ray(Vec3(0, 0, 3), Vec3(0, 0, -1))
    hit = b.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 2.0) < 1e-6  # front face at z=1, distance = 3-1 = 2


def test_box_miss():
    b = Box(Vec3(-1, -1, -1), Vec3(1, 1, 1), MAT)
    r = Ray(Vec3(0, 5, 3), Vec3(0, 0, -1))  # too high, misses
    assert b.hit(r, 1e-4, 1e10) is None


def test_box_inside_ray():
    # Ray starting inside the box should hit the exit face
    b = Box(Vec3(-1, -1, -1), Vec3(1, 1, 1), MAT)
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, 1))  # origin inside, going +z
    hit = b.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 1.0) < 1e-6  # exit at z=1


def test_box_hit_different_faces():
    b = Box(Vec3(0, 0, 0), Vec3(2, 2, 2), MAT)
    # Hit -x face
    r = Ray(Vec3(-3, 1, 1), Vec3(1, 0, 0))
    h = b.hit(r, 1e-4, 1e10)
    assert h is not None
    assert abs(h.normal.x - (-1)) < 1e-6  # outward normal faces -x

    # Hit +y face
    r = Ray(Vec3(1, 5, 1), Vec3(0, -1, 0))
    h = b.hit(r, 1e-4, 1e10)
    assert h is not None
    assert abs(h.normal.y - 1) < 1e-6  # outward normal faces +y


# ---- Plane ----

def test_plane_hit():
    p = Plane(Vec3(0, 1, 0), 0.0, MAT)  # y=0 plane
    r = Ray(Vec3(0, 5, 0), Vec3(0, -1, 0))
    hit = p.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 5.0) < 1e-6
    assert abs(hit.p.y) < 1e-6


def test_plane_miss_parallel():
    p = Plane(Vec3(0, 1, 0), 0.0, MAT)
    r = Ray(Vec3(0, 1, 0), Vec3(1, 0, 0))  # ray parallel to plane
    assert p.hit(r, 1e-4, 1e10) is None


def test_plane_front_back_face():
    p = Plane(Vec3(0, 1, 0), 0.0, MAT)
    # Ray from above — hits front face
    r = Ray(Vec3(0, 1, 0), Vec3(0, -1, 0))
    h = p.hit(r, 1e-4, 1e10)
    assert h is not None
    assert h.front_face is True
    # Ray from below — hits back face
    r2 = Ray(Vec3(0, -1, 0), Vec3(0, 1, 0))
    h2 = p.hit(r2, 1e-4, 1e10)
    assert h2 is not None
    assert h2.front_face is False


# ---- Triangle ----

def test_triangle_hit_center():
    t = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), MAT)
    r = Ray(Vec3(0, 0.3, -1), Vec3(0, 0, 1))
    hit = t.hit(r, 1e-4, 1e10)
    assert hit is not None


def test_triangle_miss_outside():
    t = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), MAT)
    r = Ray(Vec3(5, 5, -1), Vec3(0, 0, 1))  # clearly outside
    assert t.hit(r, 1e-4, 1e10) is None


def test_triangle_miss_parallel():
    t = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), MAT)
    r = Ray(Vec3(0, 0.3, 0), Vec3(1, 0, 0))  # ray in z=0 plane
    assert t.hit(r, 1e-4, 1e10) is None


def test_triangle_uv_in_range():
    t = Triangle(Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), MAT)
    r = Ray(Vec3(0.2, 0.2, -1), Vec3(0, 0, 1))
    hit = t.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert 0.0 <= hit.u <= 1.0
    assert 0.0 <= hit.v <= 1.0


def test_triangle_normal_direction():
    # Triangle in XY plane, geometric outward normal is +Z (from CCW winding).
    # Ray comes from -Z going +Z. HitRecord.normal always points against the ray,
    # so hit.normal = -Z (back-face hit, front_face=False).
    t = Triangle(Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), MAT)
    r = Ray(Vec3(0.2, 0.2, -1), Vec3(0, 0, 1))
    hit = t.hit(r, 1e-4, 1e10)
    assert hit is not None
    # Normal always opposes the incoming ray direction
    assert hit.normal.dot(r.direction) < 0


# ---- HittableList ----

def test_hittable_list_closest_hit():
    s1 = Sphere(Vec3(0, 0, -1), 0.5, MAT)
    s2 = Sphere(Vec3(0, 0, -3), 0.5, MAT)
    world = HittableList([s1, s2])
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = world.hit(r, 1e-4, 1e10)
    assert hit is not None
    assert abs(hit.t - 0.5) < 1e-6  # s1 closer


def test_hittable_list_empty():
    world = HittableList([])
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    assert world.hit(r, 1e-4, 1e10) is None


# ---- AABB ----

def test_aabb_hit():
    box = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
    r = Ray(Vec3(0, 0, 3), Vec3(0, 0, -1))
    assert box.hit(r, 1e-4, 1e10) is True


def test_aabb_miss():
    box = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
    r = Ray(Vec3(5, 0, 3), Vec3(0, 0, -1))
    assert box.hit(r, 1e-4, 1e10) is False


def test_aabb_surface_area():
    box = AABB(Vec3(0, 0, 0), Vec3(2, 3, 4))
    # SA = 2*(2*3 + 3*4 + 4*2) = 2*(6+12+8) = 52
    assert abs(box.surface_area() - 52.0) < 1e-9


def test_aabb_surrounding():
    a = AABB(Vec3(-1, -1, -1), Vec3(0, 0, 0))
    b = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
    s = AABB.surrounding(a, b)
    assert s.mn == Vec3(-1, -1, -1)
    assert s.mx == Vec3(1, 1, 1)
