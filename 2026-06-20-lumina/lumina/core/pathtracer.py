"""Unidirectional Monte Carlo path tracer with Russian Roulette."""
import random
import math
from .vec3 import Vec3
from .ray import Ray
from .materials import HitRecord


_BLACK = Vec3(0, 0, 0)
_RR_THRESHOLD = 3   # start Russian Roulette after this many bounces
_RR_PROB = 0.85     # survive probability


def trace_path(ray, world, sky_fn, max_depth=16):
    """
    Unidirectional path tracer.
    Accumulates throughput along the path; terminates via Russian Roulette.
    Returns a Vec3 radiance estimate.
    """
    colour = Vec3(0, 0, 0)
    throughput = Vec3(1, 1, 1)

    for depth in range(max_depth):
        rec = HitRecord()
        if not world.hit(ray, 0.001, 1e9, rec):
            colour += throughput * sky_fn(ray)
            break

        mat = rec.material

        # Add emitted light (area lights, emissive surfaces)
        emitted = mat.emitted(rec.u, rec.v, rec.p)
        colour += throughput * emitted

        # Scatter
        result = mat.scatter(ray, rec)
        if result is None:
            break   # emissive or absorption

        # Russian Roulette after a few bounces
        if depth >= _RR_THRESHOLD:
            survive = max(result.attenuation.x,
                          result.attenuation.y,
                          result.attenuation.z)
            survive = min(survive, _RR_PROB)
            if random.random() > survive:
                break
            throughput *= (1.0 / survive)

        throughput *= result.attenuation
        ray = result.ray

    return colour


def render_path(world, camera, sky_fn,
                width, height, samples_per_pixel,
                max_depth=16, progress_cb=None):
    """
    Full-image path trace.  Returns flat list of Vec3 (length = width*height),
    row-major, top to bottom.
    """
    pixels = []
    inv_spp = 1.0 / samples_per_pixel
    inv_w = 1.0 / width
    inv_h = 1.0 / height

    for row in range(height - 1, -1, -1):
        if progress_cb:
            progress_cb(height - 1 - row, height)
        for col in range(width):
            acc = Vec3(0, 0, 0)
            for _ in range(samples_per_pixel):
                u = (col + random.random()) * inv_w
                v = (row + random.random()) * inv_h
                ray = camera.get_ray(u, v)
                acc += trace_path(ray, world, sky_fn, max_depth)
            pixels.append(acc * inv_spp)
    return pixels


def render_whitted_full(world, camera, lights, sky_colour,
                        width, height, samples=1,
                        max_depth=8, progress_cb=None):
    """
    Full-image Whitted render (AA via jitter, soft shadows via area light sampling).
    """
    from .whitted import trace_whitted
    pixels = []
    inv_w = 1.0 / width
    inv_h = 1.0 / height
    inv_s = 1.0 / samples

    for row in range(height - 1, -1, -1):
        if progress_cb:
            progress_cb(height - 1 - row, height)
        for col in range(width):
            acc = Vec3(0, 0, 0)
            for _ in range(samples):
                u = (col + (random.random() if samples > 1 else 0.5)) * inv_w
                v = (row + (random.random() if samples > 1 else 0.5)) * inv_h
                ray = camera.get_ray(u, v)
                acc += trace_whitted(ray, world, lights, sky_colour,
                                     depth=0, max_depth=max_depth)
            pixels.append(acc * inv_s)
    return pixels
