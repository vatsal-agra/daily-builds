#!/usr/bin/env python3
"""Lumina — Monte Carlo Path Tracer

Usage:
  python lumina.py render  [scene] [options]
  python lumina.py preview [scene] [options]
  python lumina.py demo    [options]
  python lumina.py info    [scene]
  python lumina.py bench   [scene] [options]

Scenes: spheres (default), cornell, glass, showcase, or path/to/scene.json

Options:
  -W, --width INT       Image width  (default: 800)
  -H, --height INT      Image height (default: 450 or 800 for cornell)
  -s, --spp INT         Samples per pixel (default: 64)
  -d, --depth INT       Max bounce depth (default: 8)
  -o, --output FILE     Output PNG path (default: <scene>.png)
  --simple              Use simple path tracing (no NEE/MIS)
  --aces                ACES filmic tone mapping (default: Reinhard)
  --exposure FLOAT      Pre-tone-map exposure multiplier (default: 1.0)
  --seed INT            Random seed for reproducible renders
"""
import argparse
import os
import sys
import time
import random as _rng

from vec3 import Vec3
from scene import PRESETS, load_scene
from renderer import render
from output import tone_map, write_png, pixel_stats


def progress_bar(done: int, total: int, width: int = 40):
    frac = done / max(total - 1, 1)
    filled = int(frac * width)
    bar = '#' * filled + '-' * (width - filled)
    pct = frac * 100
    print(f"\r  [{bar}] {pct:5.1f}%", end='', flush=True)


def make_progress(quiet: bool):
    if quiet:
        return None
    start = [time.time()]

    def cb(done, total):
        elapsed = time.time() - start[0]
        progress_bar(done, total)
        if done == total - 1:
            print(f"  {elapsed:.1f}s")

    return cb


def resolve_scene(name: str):
    if os.path.isfile(name):
        return load_scene(name)
    if name in PRESETS:
        return PRESETS[name]()
    raise SystemExit(f"Error: Unknown scene {name!r}. "
                     f"Valid presets: {', '.join(PRESETS)}\n"
                     f"Or provide a path to a JSON scene file.")


def cmd_render(args):
    scene_name = args.scene
    scene, camera = resolve_scene(scene_name)

    width = args.width or 800
    height = args.height or (800 if scene_name == 'cornell' else 450)

    spp = args.spp
    depth = args.depth
    out = args.output or f"{scene_name}.png"
    tone = 'aces' if args.aces else 'reinhard'
    exposure = args.exposure
    use_nee = not args.simple

    if args.seed is not None:
        _rng.seed(args.seed)

    print(f"Lumina — rendering '{scene_name}'")
    print(f"  {width}×{height} px | {spp} spp | depth {depth} | "
          f"{'NEE+MIS' if use_nee else 'simple PT'} | {tone} tone map")
    print(f"  Output: {out}")

    t0 = time.time()
    pixels = render(scene, camera, width, height, spp, depth,
                    use_nee=use_nee,
                    progress_cb=make_progress(args.quiet))
    elapsed = time.time() - t0

    stats = pixel_stats(pixels)
    pixels_8 = tone_map(pixels, tone, exposure)
    meta = {
        'scene': scene_name,
        'width': width, 'height': height,
        'spp': spp, 'max_depth': depth,
        'nee_mis': use_nee,
        'tone_map': tone,
        'exposure': exposure,
        'render_time_s': round(elapsed, 2),
        'mean_luminance': round(stats.get('mean_luminance', 0), 4),
        'max_luminance': round(stats.get('max_luminance', 0), 4),
    }
    write_png(out, pixels_8, width, height, metadata=meta)

    mrps = (width * height * spp) / max(elapsed, 1e-6) / 1e6
    print(f"\n  Done in {elapsed:.1f}s  ({mrps:.2f} Mrays/s)")
    print(f"  Mean luminance: {stats.get('mean_luminance', 0):.4f}")
    print(f"  Saved: {out}")


def cmd_preview(args):
    args.width = args.width or 320
    args.height = args.height or (320 if args.scene == 'cornell' else 180)
    args.spp = args.spp if args.spp != 64 else 8
    args.depth = args.depth if args.depth != 8 else 4
    args.output = args.output or f"{args.scene}_preview.png"
    cmd_render(args)


def cmd_demo(args):
    scenes = list(PRESETS.keys())
    w = args.width or 240
    h = args.height or (240 if True else 135)
    spp = args.spp if args.spp != 64 else 16

    print("Lumina demo — rendering all preset scenes")
    print(f"  Size: {w}×{h}  SPP: {spp}\n")

    results = []
    for name in scenes:
        scene, camera = PRESETS[name]()
        hh = w if name == 'cornell' else max(1, w * 9 // 16)
        out = f"{name}_demo.png"
        t0 = time.time()
        print(f"  [{name}] ...")
        pixels = render(scene, camera, w, hh, spp, args.depth,
                        use_nee=not args.simple,
                        progress_cb=None)
        elapsed = time.time() - t0
        pixels_8 = tone_map(pixels, 'aces' if args.aces else 'reinhard', args.exposure)
        write_png(out, pixels_8, w, hh)
        print(f"    Done in {elapsed:.1f}s → {out}")
        results.append((name, out, elapsed))

    print("\nDemo complete:")
    for name, out, t in results:
        print(f"  {name:12} {out}  ({t:.1f}s)")


def cmd_info(args):
    scene_name = args.scene
    scene, camera = resolve_scene(scene_name)

    from geometry import BVHNode, HittableList
    root = scene._root
    name_type = type(root).__name__

    def count_nodes(node, depth=0):
        if isinstance(node, BVHNode):
            l_n, l_d = count_nodes(node.left, depth + 1)
            r_n, r_d = count_nodes(node.right, depth + 1) if node.right else (0, depth)
            return l_n + r_n + 1, max(l_d, r_d)
        return 1, depth

    n_nodes, max_depth = count_nodes(root)

    print(f"Scene: {scene_name}")
    print(f"  BVH type:       {name_type}")
    print(f"  BVH nodes:      {n_nodes}")
    print(f"  BVH max depth:  {max_depth}")
    print(f"  Emissive objs:  {len(scene.emissives)}")
    box = root.bounding_box()
    print(f"  World bounds:   "
          f"[{box.min_p.x:.1f},{box.min_p.y:.1f},{box.min_p.z:.1f}] — "
          f"[{box.max_p.x:.1f},{box.max_p.y:.1f},{box.max_p.z:.1f}]")
    print(f"  Camera at:      {camera.origin}")


def cmd_bench(args):
    scene_name = args.scene
    scene, camera = resolve_scene(scene_name)

    sizes = [(64, 36, 4), (128, 72, 8), (256, 144, 16)]
    if args.width:
        w = args.width
        h = args.height or (w if scene_name == 'cornell' else w * 9 // 16)
        spp = args.spp
        sizes = [(w, h, spp)]

    print(f"Benchmark: {scene_name}")
    for w, h, spp in sizes:
        t0 = time.time()
        pixels = render(scene, camera, w, h, spp, args.depth,
                        use_nee=not args.simple, progress_cb=None)
        elapsed = time.time() - t0
        mrps = (w * h * spp) / max(elapsed, 1e-6) / 1e6
        print(f"  {w:4}×{h:3} spp={spp:3}  "
              f"{elapsed:6.2f}s  {mrps:.3f} Mrays/s")


# ── Argument parsing ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Lumina — Monte Carlo Path Tracer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest='command')

    def add_common(sp):
        sp.add_argument('scene', nargs='?', default='spheres',
                        help='Scene name or JSON file')
        sp.add_argument('-W', '--width', type=int, default=None)
        sp.add_argument('-H', '--height', type=int, default=None)
        sp.add_argument('-s', '--spp', type=int, default=64)
        sp.add_argument('-d', '--depth', type=int, default=8)
        sp.add_argument('-o', '--output', default=None)
        sp.add_argument('--simple', action='store_true',
                        help='Use simple path tracing (disable NEE/MIS)')
        sp.add_argument('--aces', action='store_true',
                        help='ACES filmic tone mapping')
        sp.add_argument('--exposure', type=float, default=1.0)
        sp.add_argument('--seed', type=int, default=None)
        sp.add_argument('-q', '--quiet', action='store_true')
        return sp

    add_common(sub.add_parser('render', help='Render a scene to PNG'))
    add_common(sub.add_parser('preview', help='Quick low-quality preview'))

    dp = sub.add_parser('demo', help='Render all preset scenes')
    dp.add_argument('-W', '--width', type=int, default=None)
    dp.add_argument('-H', '--height', type=int, default=None)
    dp.add_argument('-s', '--spp', type=int, default=64)
    dp.add_argument('-d', '--depth', type=int, default=8)
    dp.add_argument('--simple', action='store_true')
    dp.add_argument('--aces', action='store_true')
    dp.add_argument('--exposure', type=float, default=1.0)
    dp.add_argument('-q', '--quiet', action='store_true')

    ip = sub.add_parser('info', help='Show scene statistics')
    ip.add_argument('scene', nargs='?', default='spheres')

    add_common(sub.add_parser('bench', help='Benchmark rendering performance'))

    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(0)

    dispatch = {
        'render':  cmd_render,
        'preview': cmd_preview,
        'demo':    cmd_demo,
        'info':    cmd_info,
        'bench':   cmd_bench,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
