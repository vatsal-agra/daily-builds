"""Tests for Lumen path tracer."""
import math
import struct
import sys
import os
import zlib
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lumen as L


# ─── Vec3 / math helpers ──────────────────────────────────────────────────────

def test_v3_broadcast():
    a = L.v3(1.0)
    assert a.shape == (3,)
    assert np.allclose(a, [1.0, 1.0, 1.0])


def test_v3_xyz():
    a = L.v3(1, 2, 3)
    assert np.allclose(a, [1.0, 2.0, 3.0])


def test_normalize():
    v = L.normalize(np.array([3.0, 0.0, 0.0]))
    assert np.allclose(v, [1.0, 0.0, 0.0])


def test_normalize_zero_safe():
    v = L.normalize(np.array([0.0, 0.0, 0.0]))
    assert np.allclose(v, [0.0, 0.0, 1.0])


def test_reflect():
    d = np.array([1.0, -1.0, 0.0]) / math.sqrt(2)
    n = np.array([0.0, 1.0, 0.0])
    r = L.reflect(d, n)
    assert np.allclose(r, [1.0 / math.sqrt(2), 1.0 / math.sqrt(2), 0.0])


def test_schlick_zero_angle():
    # schlick(0, eta) → r0 only
    eta = 1.5
    r0 = ((1 - eta) / (1 + eta)) ** 2
    assert math.isclose(L.schlick(1.0, eta), r0, rel_tol=1e-9)


def test_schlick_grazing():
    # At grazing angle (cos=0), schlick → 1.0
    assert math.isclose(L.schlick(0.0, 1.5), 1.0, rel_tol=1e-9)


def test_refract_basic():
    # Ray straight down into glass
    d = np.array([0.0, -1.0, 0.0])
    n = np.array([0.0,  1.0, 0.0])
    r = L.refract(d, n, 1.0 / 1.5)
    assert r is not None
    assert np.allclose(r, [0.0, -1.0, 0.0], atol=1e-6)


def test_refract_tir():
    # Total internal reflection: ray at steep angle in dense medium
    d = L.normalize(np.array([1.0, -0.1, 0.0]))
    n = np.array([0.0,  1.0, 0.0])
    r = L.refract(d, n, 1.5)  # dense→air, large eta ratio
    assert r is None


# ─── ONB ─────────────────────────────────────────────────────────────────────

def test_onb_orthonormal():
    n = L.normalize(np.array([1.0, 2.0, 3.0]))
    onb = L.ONB(n)
    assert np.allclose(np.dot(onb.u, onb.v), 0.0, atol=1e-10)
    assert np.allclose(np.dot(onb.u, onb.w), 0.0, atol=1e-10)
    assert np.allclose(np.dot(onb.v, onb.w), 0.0, atol=1e-10)
    assert np.isclose(np.linalg.norm(onb.u), 1.0, atol=1e-10)
    assert np.isclose(np.linalg.norm(onb.v), 1.0, atol=1e-10)
    assert np.isclose(np.linalg.norm(onb.w), 1.0, atol=1e-10)


# ─── Textures ─────────────────────────────────────────────────────────────────

def test_solid_color():
    tex = L.SolidColor([0.2, 0.4, 0.6])
    assert np.allclose(tex.value(0, 0, L.v3(0)), [0.2, 0.4, 0.6])


def test_checker_alternates():
    tex = L.CheckerTexture([1, 0, 0], [0, 1, 0], scale=math.pi)
    p1 = np.array([0.5, 0.5, 0.5])
    p2 = np.array([1.5, 0.5, 0.5])
    # They should differ (different checker squares)
    v1 = tex.value(0, 0, p1)
    v2 = tex.value(0, 0, p2)
    assert not np.allclose(v1, v2)


def test_perlin_range():
    rng = np.random.default_rng(42)
    tex = L.PerlinTexture([1, 1, 1], [0, 0, 0], scale=3.0, turbulence=4)
    for _ in range(50):
        p = rng.uniform(-5, 5, 3)
        val = tex.value(0, 0, p)
        assert np.all(val >= 0.0)
        assert np.all(val <= 1.0)


# ─── AABB ─────────────────────────────────────────────────────────────────────

def test_aabb_hit_inside():
    box = L.AABB([0, 0, 0], [1, 1, 1])
    ray = L.Ray(np.array([0.5, 0.5, -1.0]), np.array([0.0, 0.0, 1.0]))
    assert box.hit(ray, 0.0, 10.0)


def test_aabb_miss():
    box = L.AABB([0, 0, 0], [1, 1, 1])
    ray = L.Ray(np.array([2.0, 0.5, -1.0]), np.array([0.0, 0.0, 1.0]))
    assert not box.hit(ray, 0.0, 10.0)


def test_aabb_surround():
    a = L.AABB([0, 0, 0], [1, 1, 1])
    b = L.AABB([2, 2, 2], [3, 3, 3])
    s = L.AABB.surround(a, b)
    assert np.allclose(s.lo, [0, 0, 0])
    assert np.allclose(s.hi, [3, 3, 3])


# ─── Sphere ───────────────────────────────────────────────────────────────────

def test_sphere_hit_front():
    mat = L.Lambertian([1, 0, 0])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    ray = L.Ray(np.array([0.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = s.hit(ray, 0.0, 100.0)
    assert h is not None
    assert math.isclose(h.t, 4.0, abs_tol=1e-6)
    assert h.front_face


def test_sphere_miss():
    mat = L.Lambertian([1, 0, 0])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    ray = L.Ray(np.array([0.0, 2.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    assert s.hit(ray, 0.0, 100.0) is None


def test_sphere_hit_inside_is_backface():
    mat = L.Lambertian([1, 0, 0])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    ray = L.Ray(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    h = s.hit(ray, 0.0, 100.0)
    assert h is not None
    assert not h.front_face  # inside → back face


# ─── Quad ─────────────────────────────────────────────────────────────────────

def test_quad_hit():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    q = L.Quad([0, 0, 0], [1, 0, 0], [0, 1, 0], mat)
    ray = L.Ray(np.array([0.5, 0.5, -1.0]), np.array([0.0, 0.0, 1.0]))
    h = q.hit(ray, 0.0, 10.0)
    assert h is not None
    assert math.isclose(h.t, 1.0, abs_tol=1e-6)


def test_quad_miss_outside():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    q = L.Quad([0, 0, 0], [1, 0, 0], [0, 1, 0], mat)
    ray = L.Ray(np.array([2.0, 0.5, -1.0]), np.array([0.0, 0.0, 1.0]))
    h = q.hit(ray, 0.0, 10.0)
    assert h is None


def test_quad_parallel_miss():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    q = L.Quad([0, 0, 0], [1, 0, 0], [0, 1, 0], mat)
    ray = L.Ray(np.array([0.5, 0.5, 0.0]), np.array([1.0, 0.0, 0.0]))  # parallel to plane
    h = q.hit(ray, 0.0, 10.0)
    assert h is None


# ─── Box ──────────────────────────────────────────────────────────────────────

def test_box_hit():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    b = L.Box([0, 0, 0], [1, 1, 1], mat)
    ray = L.Ray(np.array([0.5, 0.5, -2.0]), np.array([0.0, 0.0, 1.0]))
    h = b.hit(ray, 0.0, 10.0)
    assert h is not None
    assert h.t < 10.0


def test_box_outward_normal_front():
    """Front face (-Z side) should have normal pointing in -Z."""
    mat = L.Lambertian([0.5, 0.5, 0.5])
    b = L.Box([0, 0, 0], [1, 1, 1], mat)
    ray = L.Ray(np.array([0.5, 0.5, -2.0]), np.array([0.0, 0.0, 1.0]))
    h = b.hit(ray, 0.0, 10.0)
    assert h is not None
    assert h.front_face
    assert h.normal[2] < 0  # outward normal points toward viewer (-Z)


def test_box_outward_normal_top():
    """Top face (+Y side) should have normal pointing in +Y."""
    mat = L.Lambertian([0.5, 0.5, 0.5])
    b = L.Box([0, 0, 0], [1, 1, 1], mat)
    ray = L.Ray(np.array([0.5, 2.0, 0.5]), np.array([0.0, -1.0, 0.0]))
    h = b.hit(ray, 0.0, 10.0)
    assert h is not None
    assert h.front_face
    assert h.normal[1] > 0  # outward normal points up (+Y)


# ─── BVH ──────────────────────────────────────────────────────────────────────

def test_bvh_single_object():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    bvh = L.BVH([s])
    ray = L.Ray(np.array([0.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = bvh.hit(ray, 0.0, 100.0)
    assert h is not None


def test_bvh_multiple_objects():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    objs = [L.Sphere([i * 3.0, 0, 0], 1.0, mat) for i in range(5)]
    bvh = L.BVH(objs)
    # Hit the middle sphere
    ray = L.Ray(np.array([6.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = bvh.hit(ray, 0.0, 100.0)
    assert h is not None


def test_bvh_miss():
    mat = L.Lambertian([0.5, 0.5, 0.5])
    objs = [L.Sphere([i * 3.0, 0, 0], 1.0, mat) for i in range(3)]
    bvh = L.BVH(objs)
    ray = L.Ray(np.array([0.0, 50.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = bvh.hit(ray, 0.0, 100.0)
    assert h is None


# ─── Materials ────────────────────────────────────────────────────────────────

def test_lambertian_scatter():
    rng = np.random.default_rng(0)
    mat = L.Lambertian([0.8, 0.2, 0.2])
    ray = L.Ray(np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0]))
    hit = L.Hit(1.0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                True, mat)
    result = mat.scatter(ray, hit, rng)
    assert result is not None
    scattered, attenuation, is_specular = result
    assert not is_specular
    assert np.allclose(attenuation, [0.8, 0.2, 0.2])


def test_lambertian_no_emission():
    mat = L.Lambertian([1, 1, 1])
    assert np.allclose(mat.emitted(0, 0, L.v3(0)), [0, 0, 0])


def test_metal_scatter_direction():
    rng = np.random.default_rng(0)
    mat = L.Metal([0.8, 0.8, 0.8], roughness=0.0)
    ray = L.Ray(np.array([0.0, 0.0, -1.0]),
                L.normalize(np.array([0.0, -1.0, 1.0])))
    hit = L.Hit(1.0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                True, mat)
    result = mat.scatter(ray, hit, rng)
    assert result is not None
    scattered, _, is_specular = result
    assert is_specular
    # Reflected ray should go upward (positive y component)
    assert scattered.direction[1] > 0


def test_metal_roughness_zero_is_mirror():
    """Roughness=0 should produce exact mirror reflection."""
    rng = np.random.default_rng(0)
    mat = L.Metal([1, 1, 1], roughness=0.0)
    d = L.normalize(np.array([0.5, -0.5, 0.0]))
    ray = L.Ray(np.array([0.0, 1.0, 0.0]), d)
    hit = L.Hit(1.0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                True, mat)
    result = mat.scatter(ray, hit, rng)
    assert result is not None
    scattered, _, _ = result
    expected = L.normalize(L.reflect(d, np.array([0.0, 1.0, 0.0])))
    assert np.allclose(scattered.direction, expected, atol=1e-6)


def test_dielectric_transmit():
    rng = np.random.default_rng(42)
    mat = L.Dielectric(1.5)
    # Ray straight down → should mostly transmit (small Fresnel at normal incidence)
    ray = L.Ray(np.array([0.0, 1.0, 0.0]), np.array([0.0, -1.0, 0.0]))
    hit = L.Hit(1.0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                True, mat)
    results = [mat.scatter(ray, hit, rng) for _ in range(30)]
    # Most should transmit (direction[1] < 0)
    transmitted = sum(1 for r in results if r[0].direction[1] < 0)
    assert transmitted >= 20  # most should transmit


def test_diffuse_light_emits():
    mat = L.DiffuseLight([1.0, 0.5, 0.2], intensity=2.0)
    em = mat.emitted(0, 0, L.v3(0))
    assert np.allclose(em, [2.0, 1.0, 0.4])


def test_diffuse_light_no_scatter():
    mat = L.DiffuseLight([1, 1, 1])
    ray = L.Ray(L.v3(0), L.v3(0, 0, 1))
    hit = L.Hit(1.0, L.v3(0), L.v3(0, 1, 0), True, mat)
    assert mat.scatter(ray, hit, None) is None


# ─── Transforms ───────────────────────────────────────────────────────────────

def test_translate_hit():
    mat = L.Lambertian([1, 1, 1])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    ts = L.Translate(s, [5, 0, 0])
    ray = L.Ray(np.array([5.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = ts.hit(ray, 0.0, 100.0)
    assert h is not None
    assert math.isclose(h.p[0], 5.0, abs_tol=0.1)


def test_translate_miss_original():
    mat = L.Lambertian([1, 1, 1])
    s = L.Sphere([0, 0, 0], 1.0, mat)
    ts = L.Translate(s, [5, 0, 0])
    # Ray aimed at original position (0,0,0) → should miss translated sphere
    ray = L.Ray(np.array([0.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = ts.hit(ray, 0.0, 100.0)
    assert h is None


def test_rotate_y_identity():
    mat = L.Lambertian([1, 1, 1])
    s = L.Sphere([1, 0, 0], 0.5, mat)
    rs = L.RotateY(s, 0.0)  # 0° rotation
    ray = L.Ray(np.array([1.0, 0.0, -5.0]), np.array([0.0, 0.0, 1.0]))
    h = rs.hit(ray, 0.0, 100.0)
    assert h is not None


# ─── Camera ───────────────────────────────────────────────────────────────────

def test_camera_center_ray():
    cam = L.Camera(
        lookfrom=[0, 0, -5], lookat=[0, 0, 0], vup=[0, 1, 0],
        vfov_deg=90, aspect=1.0
    )
    rng = np.random.default_rng(0)
    ray = cam.get_ray(0.5, 0.5, rng)
    # Center ray should point roughly in +Z
    assert ray.direction[2] > 0.9


def test_camera_dof_offset():
    """With aperture>0, ray origins should spread out from center."""
    rng = np.random.default_rng(0)
    cam = L.Camera(
        lookfrom=[0, 0, -5], lookat=[0, 0, 0], vup=[0, 1, 0],
        vfov_deg=90, aspect=1.0, aperture=2.0, focus_dist=5.0
    )
    origins = [cam.get_ray(0.5, 0.5, rng).origin for _ in range(20)]
    xs = [o[0] for o in origins]
    # Origins should not all be the same (aperture causes spread)
    assert max(xs) - min(xs) > 1e-6


# ─── Path tracer ──────────────────────────────────────────────────────────────

def test_path_trace_black_background():
    world = L.World([L.Sphere([0, 0, 5], 1.0, L.Lambertian([1, 0, 0]))])
    world.build_bvh()
    rng = np.random.default_rng(0)
    ray = L.Ray(np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))  # misses sphere
    col = L.path_trace(ray, world, [], L._bg_black, 5, rng)
    assert np.allclose(col, [0, 0, 0])


def test_path_trace_hits_light():
    """Ray aimed directly at a light should return nonzero color."""
    light = L.DiffuseLight([1.0, 1.0, 1.0], intensity=5.0)
    quad = L.Quad([-1, -1, 5], [2, 0, 0], [0, 2, 0], light)
    world = L.World([quad])
    world.build_bvh()
    rng = np.random.default_rng(0)
    ray = L.Ray(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    col = L.path_trace(ray, world, [], L._bg_black, 5, rng)
    assert np.all(col > 0)


def test_path_trace_sky_background():
    world = L.World()
    world.build_bvh()
    rng = np.random.default_rng(0)
    ray = L.Ray(np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))
    col = L.path_trace(ray, world, [], L._bg_sky, 5, rng)
    assert np.any(col > 0)


def test_path_trace_energy_conservation():
    """White lambertian sphere should reflect ≤ incoming energy."""
    rng = np.random.default_rng(0)
    mat = L.Lambertian([1.0, 1.0, 1.0])
    sphere = L.Sphere([0, 0, 0], 1.0, mat)
    world = L.World([sphere])
    world.build_bvh()
    total = 0.0
    n = 200
    for _ in range(n):
        d = L.normalize(rng.standard_normal(3))
        ray = L.Ray(d * 5.0, -d)
        col = L.path_trace(ray, world, [], L._bg_black, 10, rng)
        total += float(col.mean())
    avg = total / n
    assert avg <= 1.01  # should not create energy


# ─── PNG encoder ─────────────────────────────────────────────────────────────

def test_png_valid_header():
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    img[0, 0] = [255, 0, 0]
    png = L.encode_png(img)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_png_ihdr_dimensions():
    img = np.zeros((16, 32, 3), dtype=np.uint8)
    png = L.encode_png(img)
    # IHDR starts at byte 16, width at byte 16, height at 20
    w = struct.unpack(">I", png[16:20])[0]
    h = struct.unpack(">I", png[20:24])[0]
    assert w == 32
    assert h == 16


def test_png_roundtrip_decompressible():
    """The IDAT chunk must decompress without error."""
    img = np.random.randint(0, 256, (8, 8, 3), dtype=np.uint8)
    png = L.encode_png(img)
    # Find IDAT chunk: 4-byte len + 4-byte type = 8 bytes from pos 33
    pos = 8  # skip sig
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos+4])[0]
        ctype = png[pos+4:pos+8]
        data = png[pos+8:pos+8+length]
        if ctype == b"IDAT":
            decompressed = zlib.decompress(data)
            assert len(decompressed) == 8 * (8 * 3 + 1)  # rows × (filter + pixels)
            return
        pos += 12 + length
    pytest.fail("No IDAT chunk found")


# ─── Tone mapping ─────────────────────────────────────────────────────────────

def test_aces_clamps_to_unit():
    x = np.array([0.0, 0.5, 1.0, 5.0, 100.0])
    y = L.aces_tonemap(x)
    assert np.all(y >= 0.0)
    assert np.all(y <= 1.0)


def test_to_uint8_range():
    linear = np.random.rand(10, 10, 3).astype(float)
    out = L.to_uint8(linear)
    assert out.dtype == np.uint8
    assert out.min() >= 0
    assert out.max() <= 255


# ─── Scene constructors ───────────────────────────────────────────────────────

def test_cornell_box_constructs():
    world, lights, bg, cam = L.make_cornell_box()
    assert len(world.objects) > 0
    assert len(lights) > 0
    assert bg is L._bg_black


def test_spheres_scene_constructs():
    world, lights, bg, cam = L.make_spheres_scene()
    assert len(world.objects) > 0
    assert bg is L._bg_sky


def test_caustic_scene_constructs():
    world, lights, bg, cam = L.make_caustic_scene()
    assert len(lights) > 0


# ─── End-to-end render (tiny) ─────────────────────────────────────────────────

@pytest.mark.parametrize("scene", ["cornell", "spheres", "caustic"])
def test_e2e_render_nonblack(scene):
    """Render a 16×16@2spp image and verify it's not all black."""
    cam = L._DEFAULT_CAMS[scene]
    cam.aspect = 1.0
    img = L.render(scene, None, cam, 16, 16, 2, max_depth=4,
                   workers=1, verbose=False)
    assert img.shape == (16, 16, 3)
    assert img.max() > 0.0, f"Scene {scene!r} rendered all-black"


def test_e2e_cornell_color_check():
    """Cornell box: left half should be redder, right half greener."""
    cam = L._DEFAULT_CAMS["cornell"]
    cam.aspect = 1.0
    img = L.render("cornell", None, cam, 24, 24, 4, max_depth=6,
                   workers=1, verbose=False)
    left  = img[:, :8,  :]   # x < 8 → should pick up red wall
    right = img[:, 16:, :]   # x > 16 → should pick up green wall
    assert left[:, :, 0].mean() > left[:, :, 1].mean(),  "Left should be redder"
    assert right[:, :, 1].mean() > right[:, :, 0].mean(), "Right should be greener"
