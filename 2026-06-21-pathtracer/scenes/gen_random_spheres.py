#!/usr/bin/env python3
"""Generate a random-sphere scene JSON (many spheres, tests BVH vs brute-force)."""
import json
import math
import random
import sys


def gen(n=484, seed=42, spp=64, width=400, height=225):
    rng = random.Random(seed)
    objects = []

    # Ground
    objects.append({
        "type": "sphere",
        "center": [0, -1000, 0],
        "radius": 1000,
        "material": {
            "type": "lambertian",
            "albedo": {"type": "checker", "even": [0.9, 0.9, 0.9], "odd": [0.2, 0.3, 0.1], "scale": 5.0},
        },
    })

    # Random small spheres
    for i in range(-11, 12):
        for j in range(-11, 12):
            if len(objects) >= n + 1:
                break
            cx = i + 0.9 * rng.random()
            cz = j + 0.9 * rng.random()
            cy = 0.2
            if math.sqrt((cx - 4)**2 + (cz)**2) < 1.2:
                continue
            mat_r = rng.random()
            if mat_r < 0.75:
                col = [rng.random() ** 2, rng.random() ** 2, rng.random() ** 2]
                mat = {"type": "lambertian", "albedo": {"type": "solid", "color": col}}
            elif mat_r < 0.90:
                col = [rng.uniform(0.5, 1.0), rng.uniform(0.5, 1.0), rng.uniform(0.5, 1.0)]
                mat = {"type": "metal", "albedo": {"type": "solid", "color": col},
                       "roughness": rng.uniform(0, 0.2)}
            else:
                mat = {"type": "dielectric", "ior": 1.5}
            objects.append({"type": "sphere", "center": [cx, cy, cz],
                            "radius": 0.2, "material": mat})

    # Three hero spheres
    objects += [
        {"type": "sphere", "center": [0, 1, 0], "radius": 1.0,
         "material": {"type": "dielectric", "ior": 1.5}},
        {"type": "sphere", "center": [-4, 1, 0], "radius": 1.0,
         "material": {"type": "lambertian",
                      "albedo": {"type": "perlin", "color1": [0.8, 0.6, 0.2], "color2": [0.2, 0.1, 0.05], "scale": 3.0}}},
        {"type": "sphere", "center": [4, 1, 0], "radius": 1.0,
         "material": {"type": "metal",
                      "albedo": {"type": "solid", "color": [0.7, 0.6, 0.5]}, "roughness": 0.0}},
    ]

    return {
        "width": width, "height": height, "spp": spp, "max_depth": 10,
        "camera": {
            "look_from": [13, 2, 3], "look_at": [0, 0, 0], "up": [0, 1, 0],
            "vfov": 20, "aperture": 0.1, "focus_dist": 10.0,
        },
        "background": {"type": "gradient", "top": [0.5, 0.7, 1.0], "bottom": [1.0, 1.0, 1.0]},
        "objects": objects,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    scene = gen(n)
    print(json.dumps(scene, indent=2))
