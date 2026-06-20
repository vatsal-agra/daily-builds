#!/usr/bin/env python3
"""
Lumina — Ray Tracer / Path Tracer
Usage:
  python lumina.py render  <scene.json> [-o output.png] [--width W] [--height H]
                            [--samples N] [--mode path|whitted] [--tonemap aces|reinhard|clamp]
  python lumina.py bench   <scene.json>   # BVH vs brute-force timing
  python lumina.py viz                     # launch HTML scene editor server
  python lumina.py demo                   # render all example scenes
"""
import sys
import os
import time
import argparse

# Ensure package on path
sys.path.insert(0, os.path.dirname(__file__))

from lumina.core.scene_loader import load_scene
from lumina.core.pathtracer import render_path, render_whitted_full
from lumina.core.png import save_png, save_ppm


def _progress(row, total):
    pct = int(100 * row / total)
    bar = '=' * (pct // 2) + ' ' * (50 - pct // 2)
    print(f"\r  [{bar}] {pct:3d}%  row {row}/{total}", end='', flush=True)


def cmd_render(args):
    scene_path = args.scene
    if not os.path.exists(scene_path):
        print(f"Error: scene file not found: {scene_path!r}", file=sys.stderr)
        sys.exit(1)

    camera, world, lights, settings = load_scene(scene_path)

    # CLI overrides (use is not None to correctly handle 0 values)
    if args.width   is not None: settings['width']     = args.width
    if args.height  is not None: settings['height']    = args.height
    if args.samples is not None: settings['samples']   = args.samples
    if args.mode    is not None: settings['mode']      = args.mode
    if args.tonemap is not None: settings['tonemap']   = args.tonemap
    if args.depth   is not None: settings['max_depth'] = args.depth

    W  = settings['width']
    H  = settings['height']
    S  = settings['samples']
    md = settings['max_depth']

    if W <= 0 or H <= 0:
        print(f"Error: width and height must be positive (got {W}×{H})", file=sys.stderr)
        sys.exit(1)
    if S <= 0:
        print(f"Error: samples must be positive (got {S})", file=sys.stderr)
        sys.exit(1)
    mode     = settings['mode']
    tonemap  = settings['tonemap']
    sky_raw  = settings.get('sky')

    out_path = args.output or os.path.splitext(os.path.basename(scene_path))[0] + '.png'

    print(f"Lumina — {mode} mode | {W}×{H} @ {S} spp | depth {md} | {tonemap} tonemap")
    print(f"  Scene : {scene_path}")
    print(f"  Output: {out_path}")

    t0 = time.perf_counter()

    if mode == 'whitted':
        if not lights:
            print("  [warn] No lights in scene — Whitted mode will be dark. "
                  "Add lights or switch to 'path' mode.", file=sys.stderr)

        pixels = render_whitted_full(
            world=world, camera=camera, lights=lights,
            sky_colour=sky_raw,
            width=W, height=H, samples=S, max_depth=md,
            progress_cb=_progress,
        )
    else:
        from lumina.core.vec3 import Vec3

        def sky_fn(ray):
            if sky_raw is not None:
                return sky_raw
            t = 0.5 * (ray.direction.unit().y + 1.0)
            return Vec3(1, 1, 1) * (1 - t) + Vec3(0.5, 0.7, 1.0) * t

        workers = getattr(args, 'workers', None)
        pixels = render_path(
            world=world, camera=camera, sky_fn=sky_fn,
            width=W, height=H, samples_per_pixel=S, max_depth=md,
            progress_cb=_progress, workers=workers,
        )

    elapsed = time.perf_counter() - t0
    total_rays = W * H * S
    print()
    print(f"  Rendered {total_rays:,} rays in {elapsed:.2f}s  "
          f"({total_rays / elapsed:,.0f} rays/s)")

    save_png(out_path, W, H, pixels, tonemap_method=tonemap)
    kb = os.path.getsize(out_path) / 1024
    print(f"  Saved → {out_path}  ({kb:.1f} KB)")


def cmd_bench(args):
    """Compare BVH vs brute-force intersection on a given scene."""
    from lumina.core.scene_loader import load_scene
    from lumina.core.primitives import PrimitiveList
    from lumina.core.bvh import build_bvh
    from lumina.core.vec3 import Vec3
    from lumina.core.ray import Ray
    from lumina.core.materials import HitRecord
    import random, math

    scene_path = args.scene
    camera, world_bvh, lights, settings = load_scene(scene_path)

    # Collect leaf objects from the BVH for brute-force comparison
    leafs = _collect_leaves(world_bvh)
    if len(leafs) < 2:
        print(f"Scene only has {len(leafs)} primitives — BVH advantage is trivial.")
        print("For a meaningful benchmark, use a scene with many triangles (e.g. scenes/mesh.json)")

    world_brute = PrimitiveList(leafs)

    W, H = settings['width'], settings['height']
    # Generate sample rays
    n_rays = min(W * H, 2000)
    rays = []
    for row in range(H):
        for col in range(W):
            u = (col + 0.5) / W
            v = (row + 0.5) / H
            rays.append(camera.get_ray(u, v))
        if len(rays) >= n_rays:
            break
    rays = rays[:n_rays]

    def run_rays(world_):
        rec = HitRecord()
        hits = 0
        for ray in rays:
            rec2 = HitRecord()
            if world_.hit(ray, 0.001, 1e9, rec2):
                hits += 1
        return hits

    # BVH
    t0 = time.perf_counter()
    h_bvh = run_rays(world_bvh)
    t_bvh = time.perf_counter() - t0

    # Brute force
    t0 = time.perf_counter()
    h_brute = run_rays(world_brute)
    t_brute = time.perf_counter() - t0

    print(f"\nBenchmark — {n_rays} rays, {len(leafs)} primitives")
    print(f"  BVH        : {t_bvh*1000:.1f} ms  ({h_bvh} hits)")
    print(f"  Brute force: {t_brute*1000:.1f} ms  ({h_brute} hits)")
    if t_bvh > 0:
        print(f"  Speedup    : {t_brute / t_bvh:.1f}×")
    if h_bvh != h_brute:
        print(f"  [WARN] hit counts differ ({h_bvh} vs {h_brute}) — BVH may have a bug")
    else:
        print(f"  Hit counts agree: {h_bvh}")


def _collect_leaves(node):
    """Walk BVH tree, collect all leaf primitives."""
    from lumina.core.bvh import BVHNode
    if isinstance(node, BVHNode):
        return _collect_leaves(node.left) + _collect_leaves(node.right)
    from lumina.core.primitives import PrimitiveList
    if isinstance(node, PrimitiveList):
        return list(node.objects)
    return [node]


def cmd_viz(args):
    """Launch the interactive HTML scene editor."""
    from lumina.viz.editor import launch_editor
    port = getattr(args, 'port', 8765)
    launch_editor(port=port)


def cmd_demo(args):
    """Render all bundled example scenes."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    scenes_dir = os.path.join(script_dir, 'scenes')
    out_dir    = os.path.join(script_dir, 'demo_out')
    os.makedirs(out_dir, exist_ok=True)

    scenes = [
        ('whitted_demo.json', 'whitted', 4,   'aces'),
        ('spheres.json',      'path',    32,  'aces'),
        ('dof.json',          'path',    32,  'aces'),
        ('cornell.json',      'path',    64,  'aces'),
        ('showcase.json',     'path',    64,  'aces'),
        ('mesh.json',         'path',    48,  'aces'),
    ]

    for fname, mode, spp, tm in scenes:
        path = os.path.join(scenes_dir, fname)
        if not os.path.exists(path):
            print(f"  [skip] {fname} not found")
            continue
        out = os.path.join(out_dir, os.path.splitext(fname)[0] + '.png')
        print(f"\n{'─'*60}")
        print(f"  {fname}  ({mode}, {spp} spp)")

        camera, world, lights, settings = load_scene(path)
        settings['samples'] = spp
        settings['mode'] = mode
        settings['tonemap'] = tm

        W, H, S, md = settings['width'], settings['height'], settings['samples'], settings['max_depth']
        sky_raw = settings.get('sky')
        t0 = time.perf_counter()

        if mode == 'whitted':
            pixels = render_whitted_full(
                world=world, camera=camera, lights=lights,
                sky_colour=sky_raw, width=W, height=H, samples=S, max_depth=md,
                progress_cb=_progress,
            )
        else:
            from lumina.core.vec3 import Vec3
            def sky_fn(ray):
                if sky_raw is not None:
                    return sky_raw
                t2 = 0.5 * (ray.direction.unit().y + 1.0)
                return Vec3(1, 1, 1) * (1 - t2) + Vec3(0.5, 0.7, 1.0) * t2
            pixels = render_path(
                world=world, camera=camera, sky_fn=sky_fn,
                width=W, height=H, samples_per_pixel=S, max_depth=md,
                progress_cb=_progress,
            )

        elapsed = time.perf_counter() - t0
        print()
        print(f"  → {elapsed:.2f}s")
        save_png(out, W, H, pixels, tonemap_method=tm)
        print(f"  → {out}")

    print(f"\nAll demo renders saved to {out_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description='Lumina — from-scratch ray tracer / path tracer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest='command')

    # render
    p_render = sub.add_parser('render', help='Render a scene to PNG')
    p_render.add_argument('scene', help='Path to scene JSON file')
    p_render.add_argument('-o', '--output', default=None, help='Output PNG path')
    p_render.add_argument('--width',   type=int, default=None)
    p_render.add_argument('--height',  type=int, default=None)
    p_render.add_argument('--samples', type=int, default=None, help='Samples per pixel')
    p_render.add_argument('--mode',    choices=['path', 'whitted'], default=None)
    p_render.add_argument('--tonemap', choices=['aces', 'reinhard', 'clamp', 'gamma'], default=None)
    p_render.add_argument('--depth',   type=int, default=None, help='Max ray bounce depth')
    p_render.add_argument('--workers', type=int, default=None,
                          help='Worker processes for path tracing (default: CPU count)')

    # bench
    p_bench = sub.add_parser('bench', help='BVH vs brute-force benchmark')
    p_bench.add_argument('scene', help='Path to scene JSON file')

    # viz
    p_viz = sub.add_parser('viz', help='Launch interactive HTML scene editor')
    p_viz.add_argument('--port', type=int, default=8765)

    # demo
    sub.add_parser('demo', help='Render all example scenes')

    args = parser.parse_args()

    if args.command == 'render':
        cmd_render(args)
    elif args.command == 'bench':
        cmd_bench(args)
    elif args.command == 'viz':
        cmd_viz(args)
    elif args.command == 'demo':
        cmd_demo(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
