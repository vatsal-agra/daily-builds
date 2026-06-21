"""Tests for scene.py — JSON loader, edge cases, background types."""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.scene import load_scene, _gradient_bg, _solid_bg, _black_bg
from pathtracer.vec3 import Vec3
from pathtracer.ray import Ray


# ---- helpers ----

SCENES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scenes')


def _minimal_scene(**overrides):
    s = {
        "width": 4, "height": 4, "spp": 1, "max_depth": 2,
        "camera": {
            "look_from": [0, 0, 1], "look_at": [0, 0, 0], "up": [0, 1, 0],
            "vfov": 90,
        },
        "background": {"type": "solid", "color": [0, 0, 0]},
        "objects": [
            {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
             "material": {"type": "lambertian",
                          "albedo": {"type": "solid", "color": [0.5, 0.5, 0.5]}}}
        ],
    }
    s.update(overrides)
    return s


# ---- basic loading ----

def test_load_from_dict():
    scene = load_scene(_minimal_scene())
    assert scene.width == 4
    assert scene.height == 4
    assert scene.spp == 1


def test_load_from_json_file():
    data = _minimal_scene()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        scene = load_scene(fname)
        assert scene.width == 4
    finally:
        os.unlink(fname)


def test_load_spheres_classic():
    path = os.path.join(SCENES_DIR, 'spheres_classic.json')
    if os.path.exists(path):
        scene = load_scene(path)
        assert scene.width > 0
        assert scene.spp > 0


def test_load_cornell_box():
    path = os.path.join(SCENES_DIR, 'cornell_box.json')
    if os.path.exists(path):
        scene = load_scene(path)
        assert scene.width > 0


def test_load_dof_demo():
    path = os.path.join(SCENES_DIR, 'dof_demo.json')
    if os.path.exists(path):
        scene = load_scene(path)
        assert scene.camera is not None


# ---- input clamping ----

def test_spp_zero_clamped_to_one():
    scene = load_scene(_minimal_scene(spp=0))
    assert scene.spp == 1


def test_negative_spp_clamped():
    scene = load_scene(_minimal_scene(spp=-5))
    assert scene.spp == 1


def test_width_zero_clamped():
    scene = load_scene(_minimal_scene(width=0))
    assert scene.width == 1


def test_height_zero_clamped():
    scene = load_scene(_minimal_scene(height=0))
    assert scene.height == 1


def test_max_depth_zero_clamped():
    scene = load_scene(_minimal_scene(max_depth=0))
    assert scene.max_depth == 1


# ---- background types ----

def test_gradient_bg():
    bg = _gradient_bg([0.5, 0.7, 1.0], [1.0, 1.0, 1.0])
    r_up = Ray(Vec3(0, 0, 0), Vec3(0, 1, 0))
    r_dn = Ray(Vec3(0, 0, 0), Vec3(0, -1, 0))
    c_up = bg(r_up)
    c_dn = bg(r_dn)
    # Top should be more blue, bottom more white
    assert c_up.z > c_dn.z or abs(c_up.z - 1.0) < 0.01


def test_solid_bg():
    bg = _solid_bg([0.3, 0.5, 0.7])
    r = Ray(Vec3(0, 0, 0), Vec3(0, 1, 0))
    c = bg(r)
    assert abs(c.x - 0.3) < 1e-9
    assert abs(c.y - 0.5) < 1e-9
    assert abs(c.z - 0.7) < 1e-9


def test_black_bg():
    bg = _black_bg()
    r = Ray(Vec3(0, 0, 0), Vec3(1, 0, 0))
    c = bg(r)
    assert c.x == 0 and c.y == 0 and c.z == 0


def test_background_from_scene_gradient():
    scene = load_scene(_minimal_scene(
        **{"background": {"type": "gradient", "top": [0, 0, 1], "bottom": [1, 0, 0]}}
    ))
    r = Ray(Vec3(0, 0, 0), Vec3(0, 1, 0))
    c = scene.background(r)
    assert c.z > 0  # blue component


def test_background_from_scene_black():
    scene = load_scene(_minimal_scene(
        **{"background": {"type": "black"}}
    ))
    r = Ray(Vec3(0, 0, 0), Vec3(1, 0, 0))
    c = scene.background(r)
    assert c.x == 0 and c.y == 0 and c.z == 0


# ---- object types ----

def test_all_object_types():
    data = _minimal_scene()
    data["objects"] = [
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian", "albedo": {"type": "solid", "color": [0.5, 0.5, 0.5]}}},
        {"type": "box", "p_min": [1, 0, -2], "p_max": [2, 1, -1],
         "material": {"type": "metal", "albedo": {"type": "solid", "color": [0.8, 0.8, 0.8]}, "roughness": 0.1}},
        {"type": "plane", "normal": [0, 1, 0], "offset": -1.0,
         "material": {"type": "dielectric", "ior": 1.5}},
        {"type": "triangle", "v0": [0, 0, -2], "v1": [1, 0, -2], "v2": [0, 1, -2],
         "material": {"type": "diffuse_light", "color": [1, 1, 1], "intensity": 2.0}},
    ]
    scene = load_scene(data)
    assert scene.world is not None


def test_unknown_object_type_ignored():
    data = _minimal_scene()
    data["objects"].append({"type": "unknown_shape", "center": [0, 0, 0]})
    scene = load_scene(data)  # should not crash
    assert scene.world is not None


def test_texture_types():
    data = _minimal_scene()
    data["objects"] = [
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "checker",
                                 "even": [1, 1, 1], "odd": [0, 0, 0], "scale": 5.0}}},
        {"type": "sphere", "center": [0, 0, -2], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "perlin",
                                 "color1": [1, 1, 1], "color2": [0, 0, 0], "scale": 4.0}}},
    ]
    scene = load_scene(data)
    assert scene.world is not None


def test_empty_scene():
    data = _minimal_scene()
    data["objects"] = []
    scene = load_scene(data)
    assert scene.world is not None
    r = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    hit = scene.world.hit(r, 1e-4, 1e10)
    assert hit is None


def test_bvh_disabled():
    data = _minimal_scene()
    data["bvh"] = False
    scene = load_scene(data)
    assert scene.world is not None


# ---- camera ----

def test_camera_dof():
    data = _minimal_scene()
    data["camera"]["aperture"] = 0.1
    data["camera"]["focus_dist"] = 5.0
    scene = load_scene(data)
    assert scene.camera is not None


def test_camera_default_values():
    scene = load_scene({"objects": []})
    assert scene.width == 400
    assert scene.height == 225
    assert scene.spp == 64
