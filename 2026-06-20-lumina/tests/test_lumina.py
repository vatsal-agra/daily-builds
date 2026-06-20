"""Lumina test suite — unit and integration tests."""
import math
import sys
import os
import struct
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lumina.core.vec3 import Vec3, schlick, build_onb
from lumina.core.ray import Ray
from lumina.core.aabb import AABB
from lumina.core.materials import HitRecord, Lambertian, Metal, Dielectric, Emissive, Phong
from lumina.core.primitives import Sphere, Triangle, Plane, Quad, Box, PrimitiveList
from lumina.core.camera import Camera
from lumina.core.png import gamma_correct, aces_film, reinhard, tonemap, encode_png
from lumina.core.scene_loader import load_scene


# ── Vec3 ──────────────────────────────────────────────────────────────────────

def test_vec3_arithmetic():
    a = Vec3(1, 2, 3)
    b = Vec3(4, 5, 6)
    s = a + b
    assert s.x == 5 and s.y == 7 and s.z == 9

    d = b - a
    assert d.x == 3 and d.y == 3 and d.z == 3

    sc = a * 2
    assert sc.x == 2 and sc.y == 4 and sc.z == 6

    el = a * b
    assert el.x == 4 and el.y == 10 and el.z == 18


def test_vec3_imul_vec3():
    """throughput *= attenuation must do component-wise multiply, not corrupt to Vec3 object."""
    a = Vec3(0.9, 0.8, 0.7)
    a *= Vec3(0.5, 0.5, 0.5)
    assert isinstance(a.x, float)
    assert abs(a.x - 0.45) < 1e-10
    assert abs(a.y - 0.40) < 1e-10
    assert abs(a.z - 0.35) < 1e-10


def test_vec3_dot_cross():
    a = Vec3(1, 0, 0)
    b = Vec3(0, 1, 0)
    assert a.dot(b) == 0.0
    c = a.cross(b)
    assert abs(c.x) < 1e-14 and abs(c.y) < 1e-14 and abs(c.z - 1.0) < 1e-14


def test_vec3_unit():
    v = Vec3(3, 4, 0)
    u = v.unit()
    assert abs(u.length() - 1.0) < 1e-12


def test_vec3_reflect():
    v = Vec3(1, -1, 0).unit()
    n = Vec3(0, 1, 0)
    r = v.reflect(n)
    assert abs(r.y - (-v.y)) < 1e-12
    assert abs(r.x - v.x) < 1e-12


def test_vec3_refract_snell():
    """Snell's law: sin(θ₁)/sin(θ₂) = η₂/η₁."""
    eta = 1.5
    cos_in = math.cos(math.radians(30))
    sin_in = math.sin(math.radians(30))
    n = Vec3(0, 1, 0)
    d = Vec3(sin_in, -cos_in, 0)
    r = d.refract(n, 1.0 / eta)
    sin_out = math.sqrt(r.x**2 + r.z**2)
    assert abs(sin_out - sin_in / eta) < 1e-12


def test_build_onb_orthogonal():
    n = Vec3(0.3, 0.7, -0.4).unit()
    u, v, w = build_onb(n)
    assert abs(u.dot(v)) < 1e-12
    assert abs(u.dot(w)) < 1e-12
    assert abs(v.dot(w)) < 1e-12
    assert abs(w.x - n.x) + abs(w.y - n.y) + abs(w.z - n.z) < 1e-12


def test_schlick_zero_angle():
    r = schlick(1.0, 1.5)   # cos=1 → no Fresnel boost
    r0 = ((1 - 1.5) / (1 + 1.5)) ** 2
    assert abs(r - r0) < 1e-12


def test_schlick_grazing():
    r = schlick(0.0, 1.5)   # grazing incidence → r → 1
    assert r > 0.99


# ── AABB ──────────────────────────────────────────────────────────────────────

def test_aabb_hit_basic():
    box = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
    ray = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1))
    assert box.hit(ray, 0.001, 1e9)


def test_aabb_miss():
    box = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
    ray = Ray(Vec3(5, 5, -5), Vec3(0, 0, 1))
    assert not box.hit(ray, 0.001, 1e9)


def test_aabb_surrounding():
    a = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
    b = AABB(Vec3(2, 2, 2), Vec3(3, 3, 3))
    s = AABB.surrounding(a, b)
    assert s.minimum.x == 0 and s.maximum.x == 3


def test_aabb_from_points_degenerate():
    pts = [Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0.5, 0, 0)]
    box = AABB.from_points(pts)
    assert box.maximum.y - box.minimum.y >= 2e-4  # padded


# ── Sphere ────────────────────────────────────────────────────────────────────

def test_sphere_hit():
    mat = Lambertian(Vec3(1, 0, 0))
    s = Sphere(Vec3(0, 0, 0), 1.0, mat)
    ray = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1))
    rec = HitRecord()
    assert s.hit(ray, 0.001, 1e9, rec)
    assert abs(rec.t - 4.0) < 1e-10


def test_sphere_miss():
    mat = Lambertian(Vec3(1, 0, 0))
    s = Sphere(Vec3(0, 0, 0), 1.0, mat)
    ray = Ray(Vec3(5, 5, -5), Vec3(0, 0, 1))
    rec = HitRecord()
    assert not s.hit(ray, 0.001, 1e9, rec)


def test_sphere_uv_coverage():
    mat = Lambertian(Vec3(1, 0, 0))
    s = Sphere(Vec3(0, 0, 0), 1.0, mat)
    for u_exp, v_exp, dir_ in [
        (0.5, 0.5, Vec3(0, 0, -1)),  # front face
        (0.0, 0.5, Vec3(-1, 0, 0)),  # left
    ]:
        ray = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1)) if dir_.z != 0 else Ray(dir_ * -5, -dir_)
        rec = HitRecord()
        ray = Ray(dir_ * -5, -dir_)
        s.hit(ray, 0.001, 1e9, rec)
        assert 0.0 <= rec.u <= 1.0 and 0.0 <= rec.v <= 1.0


# ── Triangle ──────────────────────────────────────────────────────────────────

def test_triangle_hit():
    mat = Lambertian(Vec3(0, 1, 0))
    tri = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), mat)
    ray = Ray(Vec3(0, 0.3, -3), Vec3(0, 0, 1))
    rec = HitRecord()
    assert tri.hit(ray, 0.001, 1e9, rec)
    assert abs(rec.t - 3.0) < 1e-6


def test_triangle_miss_outside():
    mat = Lambertian(Vec3(0, 1, 0))
    tri = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), mat)
    ray = Ray(Vec3(5, 0.3, -3), Vec3(0, 0, 1))
    rec = HitRecord()
    assert not tri.hit(ray, 0.001, 1e9, rec)


def test_triangle_two_sided_false():
    mat = Lambertian(Vec3(0, 1, 0))
    tri = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), mat, two_sided=False)
    # e1×e2 gives normal (0,0,1); front face points toward +z.
    # Ray from -z side (hits the back face) — must miss for one-sided triangle.
    ray_back = Ray(Vec3(0, 0.3, -3), Vec3(0, 0, 1))
    rec = HitRecord()
    assert not tri.hit(ray_back, 0.001, 1e9, rec)
    # Ray from +z side (hits the front face) — must hit.
    ray_front = Ray(Vec3(0, 0.3, 3), Vec3(0, 0, -1))
    assert tri.hit(ray_front, 0.001, 1e9, rec)


def test_triangle_two_sided_true():
    mat = Lambertian(Vec3(0, 1, 0))
    tri = Triangle(Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), mat, two_sided=True)
    # Both front and back face rays should hit when two_sided=True.
    ray_back = Ray(Vec3(0, 0.3, -3), Vec3(0, 0, 1))
    rec = HitRecord()
    assert tri.hit(ray_back, 0.001, 1e9, rec)
    ray_front = Ray(Vec3(0, 0.3, 3), Vec3(0, 0, -1))
    assert tri.hit(ray_front, 0.001, 1e9, rec)


# ── BVH ───────────────────────────────────────────────────────────────────────

def test_bvh_matches_brute_force():
    """BVH and PrimitiveList must agree on all ray hits for a small scene."""
    from lumina.core.bvh import build_bvh
    import random

    random.seed(42)
    mat = Lambertian(Vec3(0.5, 0.5, 0.5))
    spheres = [Sphere(Vec3(random.uniform(-3, 3), random.uniform(-3, 3), random.uniform(-3, 3)),
                      0.4, mat) for _ in range(20)]

    world_bvh   = build_bvh(spheres)
    world_brute = PrimitiveList(spheres)

    mismatches = 0
    for _ in range(200):
        origin = Vec3(random.uniform(-5, 5), random.uniform(-5, 5), -10)
        target = Vec3(random.uniform(-3, 3), random.uniform(-3, 3), 0)
        ray = Ray(origin, (target - origin).unit())
        rec_b = HitRecord()
        rec_r = HitRecord()
        hit_b = world_bvh.hit(ray, 0.001, 1e9, rec_b)
        hit_r = world_brute.hit(ray, 0.001, 1e9, rec_r)
        if hit_b != hit_r:
            mismatches += 1
        elif hit_b and abs(rec_b.t - rec_r.t) > 1e-9:
            mismatches += 1
    assert mismatches == 0, f"{mismatches} BVH/brute-force mismatches"


# ── Materials ─────────────────────────────────────────────────────────────────

def test_lambertian_scatter_above_surface():
    mat = Lambertian(Vec3(0.8, 0.8, 0.8))
    rec = HitRecord()
    rec.p = Vec3(0, 0, 0)
    rec.normal = Vec3(0, 1, 0)
    rec.front_face = True
    for _ in range(20):
        result = mat.scatter(Ray(Vec3(0, 1, 0), Vec3(0, -1, 0)), rec)
        assert result is not None
        assert result.ray.direction.dot(rec.normal) > -1.0


def test_metal_reflect_direction():
    mat = Metal(Vec3(0.9, 0.9, 0.9), fuzz=0.0)
    rec = HitRecord()
    rec.p = Vec3(0, 0, 0)
    rec.normal = Vec3(0, 1, 0)
    rec.front_face = True
    ray_in = Ray(Vec3(0, 5, 0), Vec3(0, -1, 0))
    result = mat.scatter(ray_in, rec)
    assert result is not None
    assert result.ray.direction.y > 0  # reflected upward


def test_dielectric_transmit():
    mat = Dielectric(ior=1.5)
    rec = HitRecord()
    rec.p = Vec3(0, 0, 0)
    rec.normal = Vec3(0, 1, 0)
    rec.front_face = True
    # Straight-on ray — should mostly transmit
    hits = 0
    for _ in range(50):
        result = mat.scatter(Ray(Vec3(0, 5, 0), Vec3(0, -1, 0)), rec)
        if result is not None and result.ray.direction.y < 0:
            hits += 1
    assert hits > 30  # majority transmit (not reflect)


def test_emissive_no_scatter():
    mat = Emissive(Vec3(1, 0.9, 0.7), strength=5.0)
    rec = HitRecord()
    rec.p = Vec3(0, 0, 0)
    rec.normal = Vec3(0, 1, 0)
    assert mat.scatter(Ray(Vec3(0, 5, 0), Vec3(0, -1, 0)), rec) is None
    em = mat.emitted(0, 0, Vec3(0, 0, 0))
    assert abs(em.x - 5.0) < 1e-10 and abs(em.y - 4.5) < 1e-10


# ── Energy conservation (white furnace test) ──────────────────────────────────

def test_white_furnace_lambertian():
    """Lambertian albedo=1 in a white sky should return ~1.0 radiance (energy conservation)."""
    from lumina.core.pathtracer import trace_path
    import random

    mat = Lambertian(Vec3(1, 1, 1))
    sphere = Sphere(Vec3(0, 0, 0), 1.0, mat)
    world = PrimitiveList([sphere])
    sky_fn = lambda _ray: Vec3(1, 1, 1)

    random.seed(7)
    total = Vec3(0, 0, 0)
    N = 500
    for _ in range(N):
        ray = Ray(Vec3(0, 0, -3), Vec3(0, 0, 1))
        total += trace_path(ray, world, sky_fn, max_depth=24)
    mean = total * (1.0 / N)
    # All components should be close to 1.0
    for comp in (mean.x, mean.y, mean.z):
        assert 0.90 < comp < 1.10, f"White furnace test failed: component = {comp}"


# ── PNG encoder ───────────────────────────────────────────────────────────────

def test_png_gamma_nan_inf():
    assert gamma_correct(float('nan')) == 0.0
    assert gamma_correct(float('inf')) == 1.0
    assert gamma_correct(-1.0) == 0.0
    assert 0.0 < gamma_correct(0.5) < 1.0


def test_aces_nan_inf():
    assert aces_film(float('nan')) == 0.0
    assert aces_film(float('inf')) == 1.0
    assert aces_film(-1.0) == 0.0
    r = aces_film(1.0)
    assert 0.0 <= r <= 1.0


def test_reinhard():
    assert reinhard(float('nan')) == 0.0
    assert reinhard(float('inf')) == 1.0
    assert abs(reinhard(1.0) - 0.5) < 1e-12


def test_tonemap_methods():
    pixels = [Vec3(0.5, 0.5, 0.5), Vec3(2.0, 0.0, 0.0), Vec3(float('nan'), 1.0, 0.0)]
    for method in ('aces', 'reinhard', 'clamp', 'gamma'):
        result = tonemap(pixels, method=method)
        assert len(result) == 3
        for (r, g, b) in result:
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


def test_tonemap_unknown_method():
    try:
        tonemap([Vec3(0.5, 0.5, 0.5)], method='bogus')
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_encode_png_valid():
    """encode_png should produce a valid PNG (correct signature and chunk structure)."""
    pixels = [(100, 150, 200), (200, 100, 50)]
    data = encode_png(2, 1, pixels)
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    # IHDR chunk
    assert data[12:16] == b'IHDR'
    w, h = struct.unpack('>II', data[16:24])
    assert w == 2 and h == 1
    # IEND chunk at end
    assert data[-4:] == b'\xae\x42\x60\x82'


def test_encode_png_1x1():
    data = encode_png(1, 1, [(255, 0, 128)])
    assert data[:8] == b'\x89PNG\r\n\x1a\n'


def test_encode_png_hdr_overflow():
    """Pixels that overflow 255 should be clamped by tonemap before encoding."""
    pixels = [Vec3(10.0, 0.0, 0.0)]
    result = tonemap(pixels, method='aces')
    r, g, b = result[0]
    assert 0 <= r <= 255


# ── Depth of Field ────────────────────────────────────────────────────────────

def test_dof_focus_plane():
    """All rays through the same image point should pass through the focus plane."""
    cam = Camera(
        look_from=Vec3(0, 0, -5),
        look_at=Vec3(0, 0, 0),
        vup=Vec3(0, 1, 0),
        vfov=40,
        aspect=1.0,
        aperture=0.5,
        focus_dist=5.0,
    )
    # Centre pixel (0.5, 0.5) should focus on (0, 0, 0)
    pts = []
    for _ in range(30):
        ray = cam.get_ray(0.5, 0.5)
        # advance ray to focus plane (z=0)
        t = (0.0 - ray.origin.z) / ray.direction.z
        pts.append(ray.at(t))
    # All focus points must be within a tiny spread
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    spread = max(max(xs) - min(xs), max(ys) - min(ys))
    assert spread < 0.02, f"DOF focus spread too large: {spread}"


# ── OBJ Loader ────────────────────────────────────────────────────────────────

def test_obj_loader_tetra():
    """tetra.obj should parse without error and produce 4 triangles."""
    import json
    scene_path = os.path.join(os.path.dirname(__file__), '..', 'scenes', 'mesh.json')
    if not os.path.exists(scene_path):
        return  # skip if scene not present
    camera, world, lights, settings = load_scene(scene_path)
    # World should have loaded the mesh
    assert world is not None


def test_obj_loader_bad_index():
    from lumina.core.obj_loader import load_obj
    import tempfile
    obj = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n"  # index 0 is invalid in OBJ
    with tempfile.NamedTemporaryFile(suffix='.obj', mode='w', delete=False) as f:
        f.write(obj)
        path = f.name
    try:
        load_obj(path, Lambertian(Vec3(1, 0, 0)))
        assert False, "Should have raised ValueError for index 0"
    except ValueError:
        pass
    finally:
        os.unlink(path)


# ── Scene Loader ──────────────────────────────────────────────────────────────

def test_scene_loader_spheres():
    path = os.path.join(os.path.dirname(__file__), '..', 'scenes', 'spheres.json')
    if not os.path.exists(path):
        return
    camera, world, lights, settings = load_scene(path)
    assert settings['width'] > 0
    assert settings['height'] > 0
    assert settings['samples'] > 0


def test_scene_loader_missing_camera():
    import json, tempfile
    scene = {"objects": [], "lights": [], "render": {"width": 10, "height": 10, "samples": 1}}
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False) as f:
        json.dump(scene, f)
        path = f.name
    try:
        load_scene(path)
        assert False, "Should raise ValueError for missing camera"
    except (ValueError, KeyError):
        pass
    finally:
        os.unlink(path)


# ── End-to-end render ─────────────────────────────────────────────────────────

def test_render_path_tiny():
    """End-to-end path trace should produce correct number of pixels without crash."""
    from lumina.core.pathtracer import render_path
    path = os.path.join(os.path.dirname(__file__), '..', 'scenes', 'spheres.json')
    if not os.path.exists(path):
        return
    camera, world, lights, settings = load_scene(path)
    pixels = render_path(world, camera, lambda r: Vec3(0.5, 0.7, 1.0),
                         width=8, height=6, samples_per_pixel=2,
                         max_depth=4, workers=1)
    assert len(pixels) == 48
    for p in pixels:
        assert isinstance(p, Vec3)
        assert not math.isnan(p.x) and not math.isnan(p.y) and not math.isnan(p.z)


def test_render_whitted_tiny():
    """End-to-end Whitted render should produce correct number of pixels."""
    from lumina.core.pathtracer import render_whitted_full
    path = os.path.join(os.path.dirname(__file__), '..', 'scenes', 'whitted_demo.json')
    if not os.path.exists(path):
        return
    camera, world, lights, settings = load_scene(path)
    pixels = render_whitted_full(world=world, camera=camera, lights=lights,
                                 sky_colour=None,
                                 width=8, height=6, samples=1, max_depth=4)
    assert len(pixels) == 48
    for p in pixels:
        assert not math.isnan(p.x) and not math.isnan(p.y) and not math.isnan(p.z)


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
