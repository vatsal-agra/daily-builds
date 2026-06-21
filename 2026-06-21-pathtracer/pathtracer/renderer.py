"""Tile-based parallel Monte Carlo path tracer."""
import math
import random
import multiprocessing
import time

from .vec3 import Vec3


# Module-level scene state shared across fork'd workers
_world = None
_camera = None
_background = None


def _init_worker(world, camera, background):
    global _world, _camera, _background
    _world = world
    _camera = camera
    _background = background


# ---- core path tracing ----

def _trace(ray, world, background, depth, max_depth, rng):
    """Recursive path tracer. Returns radiance along the ray."""
    if depth >= max_depth:
        return Vec3(0, 0, 0)

    hit = world.hit(ray, 1e-4, math.inf)
    if hit is None:
        return background(ray)

    emitted = hit.material.emitted(hit.u, hit.v, hit.p)

    result = hit.material.scatter(ray, hit, rng)
    if result is None:
        return emitted  # emissive surface or absorbed

    scattered_ray, attenuation = result

    # Russian roulette after depth 3 for unbiased variance reduction
    if depth >= 3:
        survival = min(0.95, attenuation.luminance())
        if rng.random() > survival:
            return emitted
        attenuation = attenuation / survival

    return emitted + attenuation * _trace(scattered_ray, world, background,
                                          depth + 1, max_depth, rng)


def _render_tile(args):
    """Worker function: render a rectangular tile and return pixel data."""
    x0, y0, x1, y1, width, height, spp, max_depth, seed = args
    rng = random.Random(seed)

    pixels = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            color = Vec3(0, 0, 0)
            for s in range(spp):
                # Stratified jitter within the pixel
                u = (x + rng.random()) / width
                v = (y + rng.random()) / height
                ray = _camera.get_ray(u, 1.0 - v, rng)
                color = color + _trace(ray, _world, _background, 0, max_depth, rng)

            color = color / spp
            # Gamma-2 correction (sqrt)
            color = Vec3(
                math.sqrt(max(0.0, color.x)),
                math.sqrt(max(0.0, color.y)),
                math.sqrt(max(0.0, color.z)),
            )
            pixels.append(color)
    return x0, y0, x1, y1, pixels


def render(scene, workers=None, tile_size=16, progress=True):
    """Render the scene and return a 2-D list of Vec3 pixel colours.

    Parameters
    ----------
    scene:      Scene object (world, camera, background, width, height, spp, max_depth)
    workers:    number of worker processes (default: cpu_count())
    tile_size:  pixel size of each work unit
    progress:   print progress to stderr
    """
    width   = scene.width
    height  = scene.height
    spp     = scene.spp
    max_depth = scene.max_depth

    if workers is None:
        workers = max(1, multiprocessing.cpu_count())

    # Build tile list
    tiles = []
    seed = 0
    for y0 in range(0, height, tile_size):
        for x0 in range(0, width, tile_size):
            x1 = min(x0 + tile_size, width)
            y1 = min(y0 + tile_size, height)
            tiles.append((x0, y0, x1, y1, width, height, spp, max_depth, seed))
            seed += 1

    total = len(tiles)

    # Allocate image buffer
    image = [[Vec3(0, 0, 0)] * width for _ in range(height)]

    t_start = time.time()

    if workers == 1:
        # Single-process path — easier to debug
        _init_worker(scene.world, scene.camera, scene.background)
        done = 0
        for tile_args in tiles:
            x0, y0, x1, y1, pixels = _render_tile(tile_args)
            idx = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    image[y][x] = pixels[idx]
                    idx += 1
            done += 1
            if progress:
                _print_progress(done, total, t_start)
    else:
        ctx = multiprocessing.get_context('fork')
        with ctx.Pool(
            processes=workers,
            initializer=_init_worker,
            initargs=(scene.world, scene.camera, scene.background),
        ) as pool:
            done = 0
            for x0, y0, x1, y1, pixels in pool.imap_unordered(_render_tile, tiles):
                idx = 0
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        image[y][x] = pixels[idx]
                        idx += 1
                done += 1
                if progress:
                    _print_progress(done, total, t_start)

    if progress:
        elapsed = time.time() - t_start
        print(f"\rDone. {width}×{height} @ {spp} SPP in {elapsed:.1f}s"
              f" ({width*height*spp/elapsed/1e6:.2f} Mrays/s)", flush=True)

    return image


def _print_progress(done, total, t_start):
    pct = done / total * 100
    elapsed = time.time() - t_start
    eta = elapsed / done * (total - done) if done else 0
    print(f"\r  {pct:5.1f}%  [{done}/{total} tiles]  "
          f"elapsed {elapsed:.1f}s  ETA {eta:.1f}s    ",
          end='', flush=True)
