"""Unidirectional Monte Carlo path tracer with Russian Roulette."""
import random
import math
import os
from .vec3 import Vec3
from .ray import Ray
from .materials import HitRecord


_BLACK = Vec3(0, 0, 0)
_RR_THRESHOLD = 3   # start Russian Roulette after this many bounces
_RR_PROB = 0.85     # survive probability


def _render_row_batch(args):
    """Worker function for multiprocessing — renders a list of rows."""
    rows, width, inv_w, inv_h, spp, sky_fn, world, camera, max_depth = args
    random.seed(os.getpid() ^ (rows[0] * 6364136223846793005))
    result = []
    inv_spp = 1.0 / spp
    for row in rows:
        for col in range(width):
            acc = Vec3(0, 0, 0)
            for _ in range(spp):
                u = (col + random.random()) * inv_w
                v = (row + random.random()) * inv_h
                ray = camera.get_ray(u, v)
                acc += trace_path(ray, world, sky_fn, max_depth)
            result.append((row, col, acc * inv_spp))
    return result


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

        # Apply attenuation first, then Russian Roulette on the full throughput.
        # This ensures the RR compensation factor (1/survive) is energy-conservative:
        # survive is based on current throughput luminance, so net change ≤ 1.
        throughput *= result.attenuation
        ray = result.ray

        if depth >= _RR_THRESHOLD:
            survive = min(max(throughput.x, throughput.y, throughput.z), _RR_PROB)
            if survive <= 0 or random.random() > survive:
                break
            throughput *= (1.0 / survive)

    return colour


def render_path(world, camera, sky_fn,
                width, height, samples_per_pixel,
                max_depth=16, progress_cb=None, workers=None):
    """
    Full-image path trace.  Returns flat list of Vec3 (length = width*height),
    row-major, top to bottom.
    workers=None → auto (os.cpu_count()), workers=1 → single-threaded.
    """
    import multiprocessing

    if workers is None:
        workers = os.cpu_count() or 1

    inv_spp = 1.0 / samples_per_pixel
    inv_w = 1.0 / width
    inv_h = 1.0 / height
    rows = list(range(height - 1, -1, -1))   # top to bottom

    if workers == 1 or height <= 4:
        # Single-threaded fallback
        pixels = []
        for row in rows:
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

    # Multi-process: split rows across workers
    chunk_size = max(1, height // (workers * 4))
    batches = []
    for i in range(0, len(rows), chunk_size):
        batch = rows[i:i + chunk_size]
        batches.append((batch, width, inv_w, inv_h, samples_per_pixel,
                        sky_fn, world, camera, max_depth))

    pixel_map = {}   # (row, col) → Vec3
    completed = [0]

    try:
        ctx = multiprocessing.get_context('fork')
        with ctx.Pool(workers) as pool:
            for batch_result in pool.imap_unordered(_render_row_batch, batches):
                for (row, col, pixel) in batch_result:
                    pixel_map[(row, col)] = pixel
                completed[0] += 1
                if progress_cb:
                    done_rows = sum(1 for r in rows
                                    if any((r, c) in pixel_map for c in range(min(1, width))))
                    progress_cb(done_rows, height)
    except Exception:
        # Fall back to single-threaded on any multiprocessing failure
        return render_path(world, camera, sky_fn, width, height, samples_per_pixel,
                           max_depth=max_depth, progress_cb=progress_cb, workers=1)

    # Reassemble in row-major order (top to bottom)
    pixels = []
    for row in rows:
        for col in range(width):
            pixels.append(pixel_map.get((row, col), Vec3(0, 0, 0)))
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
