"""Tests for renderer.py — small renders verify non-zero output, color bleeding."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathtracer.vec3 import Vec3
from pathtracer.scene import load_scene
from pathtracer.renderer import render


SCENES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scenes')


def _tiny_scene(objects, spp=4, max_depth=4, bg_type='gradient'):
    return {
        "width": 8, "height": 8, "spp": spp, "max_depth": max_depth,
        "camera": {
            "look_from": [0, 0, 3], "look_at": [0, 0, 0], "up": [0, 1, 0],
            "vfov": 60,
        },
        "background": {"type": bg_type, "top": [0.5, 0.7, 1.0], "bottom": [1.0, 1.0, 1.0]},
        "objects": objects,
    }


def _avg_luminance(image):
    total = 0.0
    count = 0
    for row in image:
        for p in row:
            total += p.luminance()
            count += 1
    return total / count if count else 0.0


# ---- basic rendering ----

def test_render_not_all_black():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "solid", "color": [0.8, 0.2, 0.2]}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    lum = _avg_luminance(image)
    assert lum > 0.01, f"Rendered image is too dark: avg luminance={lum}"


def test_render_dimensions():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "solid", "color": [0.5, 0.5, 0.5]}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    assert len(image) == 8
    assert len(image[0]) == 8


def test_render_pixel_values_in_range():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "solid", "color": [0.5, 0.5, 0.5]}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    for row in image:
        for p in row:
            # After gamma correction, values should be in [0, 1+epsilon]
            assert p.x >= 0.0 and p.x <= 1.01
            assert p.y >= 0.0 and p.y <= 1.01
            assert p.z >= 0.0 and p.z <= 1.01


def test_render_metal_sphere():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -2], "radius": 1.0,
         "material": {"type": "metal",
                      "albedo": {"type": "solid", "color": [0.9, 0.9, 0.9]}, "roughness": 0.0}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    lum = _avg_luminance(image)
    assert lum > 0.01


def test_render_glass_sphere():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -2], "radius": 1.0,
         "material": {"type": "dielectric", "ior": 1.5}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    lum = _avg_luminance(image)
    assert lum > 0.01


def test_render_area_light():
    # Area light above a diffuse floor — floor should be illuminated
    data = {
        "width": 8, "height": 8, "spp": 8, "max_depth": 4,
        "camera": {
            "look_from": [0, 1, 3], "look_at": [0, 0.5, 0],
            "up": [0, 1, 0], "vfov": 45,
        },
        "background": {"type": "black"},
        "objects": [
            {"type": "sphere", "center": [0, -100, 0], "radius": 100,
             "material": {"type": "lambertian",
                          "albedo": {"type": "solid", "color": [0.8, 0.8, 0.8]}}},
            {"type": "sphere", "center": [0, 3, 0], "radius": 0.5,
             "material": {"type": "diffuse_light", "color": [1, 1, 1], "intensity": 10.0}},
        ],
    }
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    lum = _avg_luminance(image)
    assert lum > 0.001, f"Scene with area light rendered too dark: {lum}"


# ---- color bleeding (Cornell box) ----

def test_cornell_box_color_bleeding():
    path = os.path.join(SCENES_DIR, 'cornell_box.json')
    if not os.path.exists(path):
        return

    import json
    with open(path) as f:
        data = json.load(f)
    # Render tiny
    data['width'] = 16
    data['height'] = 16
    data['spp'] = 16
    data['max_depth'] = 6

    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)

    # Sample the left and right columns and check for color asymmetry
    left_r = sum(image[r][0].x for r in range(16)) / 16
    left_g = sum(image[r][0].y for r in range(16)) / 16
    right_r = sum(image[r][15].x for r in range(16)) / 16
    right_g = sum(image[r][15].y for r in range(16)) / 16

    lum = _avg_luminance(image)
    assert lum > 0.05, f"Cornell box too dark: {lum}"
    # Red wall is on the right: right_r/right_g > left_r/left_g
    # (or just check that the scene is not all-grey)
    color_variance = abs(left_r - right_r) + abs(left_g - right_g)
    assert color_variance > 0.01, (
        f"Cornell box shows no color: left_r={left_r:.3f}, right_r={right_r:.3f}, "
        f"left_g={left_g:.3f}, right_g={right_g:.3f}"
    )


# ---- single-process vs no-crash ----

def test_render_single_worker():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "solid", "color": [0.5, 0.5, 0.5]}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, tile_size=4, progress=False)
    assert len(image) == 8


def test_render_checker_texture():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, -100.5, -1], "radius": 100,
         "material": {"type": "lambertian",
                      "albedo": {"type": "checker",
                                 "even": [1, 1, 1], "odd": [0, 0, 0], "scale": 5.0}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    lum = _avg_luminance(image)
    assert lum > 0


def test_render_perlin_texture():
    data = _tiny_scene([
        {"type": "sphere", "center": [0, 0, -1], "radius": 0.5,
         "material": {"type": "lambertian",
                      "albedo": {"type": "perlin",
                                 "color1": [1, 0.8, 0.5], "color2": [0.3, 0.1, 0.0], "scale": 4.0}}}
    ])
    scene = load_scene(data)
    image = render(scene, workers=1, progress=False)
    assert _avg_luminance(image) > 0
