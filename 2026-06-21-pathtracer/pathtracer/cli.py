"""Command-line interface for the path tracer."""
import argparse
import os
import sys
import time
import json

from .scene import load_scene
from .renderer import render
from .png_writer import write_png, image_to_ppm


def cmd_render(args):
    """Render a JSON scene file."""
    if not os.path.isfile(args.scene):
        print(f"Error: scene file not found: {args.scene}", file=sys.stderr)
        sys.exit(1)

    try:
        scene = load_scene(args.scene)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Error: bad scene file — {e}", file=sys.stderr)
        sys.exit(1)

    # CLI overrides (all guarded: value > 0 after clamping in load_scene)
    if args.width  and args.width  > 0:  scene.width  = args.width
    if args.height and args.height > 0:  scene.height = args.height
    if args.spp    and args.spp    > 0:  scene.spp    = args.spp
    if args.depth  and args.depth  > 0:  scene.max_depth = args.depth

    out = args.output or _default_out(args.scene, 'png')
    fmt = args.format or ('ppm' if out.endswith('.ppm') else 'png')

    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"Rendering {scene.width}×{scene.height} @ {scene.spp} SPP "
          f"({scene.max_depth} bounces) → {out}")

    workers = args.workers if args.workers else None
    image = render(scene, workers=workers, progress=True)

    if fmt == 'ppm':
        image_to_ppm(image, out)
    else:
        write_png(image, out)
    print(f"Saved → {out}")


def cmd_demo(args):
    """Render all three built-in example scenes at small size."""
    import importlib.resources
    scenes_dir = os.path.join(os.path.dirname(__file__), '..', 'scenes')
    scenes_dir = os.path.normpath(scenes_dir)

    demos = [
        ('spheres_classic.json', 'Classic three-sphere scene'),
        ('cornell_box.json',     'Cornell Box with color bleeding'),
        ('dof_demo.json',        'Depth-of-field bokeh demo'),
    ]

    for fname, desc in demos:
        path = os.path.join(scenes_dir, fname)
        if not os.path.exists(path):
            print(f"  [skip] {fname} not found")
            continue

        scene = load_scene(path)
        scene.width  = args.width  or 200
        scene.height = args.height or 150
        scene.spp    = args.spp    or 32
        scene.max_depth = 8

        out = os.path.join(args.outdir or '.', fname.replace('.json', '.png'))
        os.makedirs(args.outdir or '.', exist_ok=True)

        print(f"\n── {desc} ({scene.width}×{scene.height} @ {scene.spp} SPP) ──")
        workers = args.workers if args.workers else None
        image = render(scene, workers=workers, progress=True)
        write_png(image, out)
        print(f"  Saved → {out}")

    print("\nDemo complete.")


def cmd_bench(args):
    """Benchmark BVH vs brute-force on a scene with many spheres."""
    import random as _random
    from .vec3 import Vec3
    from .materials import Lambertian, Metal, Dielectric
    from .shapes import Sphere, HittableList
    from .bvh import build_bvh
    from .camera import Camera
    from .scene import Scene, _gradient_bg
    from .renderer import render

    n = args.count or 100
    print(f"Generating {n} random spheres…")

    rng = _random.Random(42)
    objects = []
    for _ in range(n):
        c = Vec3(rng.uniform(-10, 10), 0.2, rng.uniform(-10, 10))
        r = rng.uniform(0.15, 0.35)
        mat_choice = rng.random()
        if mat_choice < 0.7:
            mat = Lambertian(Vec3(rng.random(), rng.random(), rng.random()))
        elif mat_choice < 0.9:
            mat = Metal(Vec3(rng.uniform(0.5, 1), rng.uniform(0.5, 1), rng.uniform(0.5, 1)),
                        rng.uniform(0, 0.3))
        else:
            mat = Dielectric(1.5)
        objects.append(Sphere(c, r, mat))

    look_from = Vec3(13, 2, 3)
    look_at   = Vec3(0,  0, 0)
    camera = Camera(look_from, look_at, Vec3(0, 1, 0), 20, 4/3)
    bg = _gradient_bg([0.5, 0.7, 1.0], [1.0, 1.0, 1.0])

    w, h, spp = 80, 60, 4

    print(f"\n[Brute-force HittableList] {n} spheres…")
    brute = HittableList(objects)
    s1 = Scene(brute, camera, bg, w, h, spp, 4)
    t0 = time.time()
    render(s1, workers=1, progress=False)
    t_brute = time.time() - t0

    print(f"[BVH with SAH] {n} spheres…")
    bvh_world = build_bvh(list(objects))
    s2 = Scene(bvh_world, camera, bg, w, h, spp, 4)
    t0 = time.time()
    render(s2, workers=1, progress=False)
    t_bvh = time.time() - t0

    speedup = t_brute / t_bvh if t_bvh > 0 else float('inf')
    print(f"\nBrute-force : {t_brute:.2f}s")
    print(f"BVH (SAH)   : {t_bvh:.2f}s")
    print(f"Speedup     : {speedup:.1f}×")


def cmd_info(args):
    """Print scene metadata."""
    scene = load_scene(args.scene)
    print(f"Scene: {args.scene}")
    print(f"  Size      : {scene.width} × {scene.height}")
    print(f"  SPP       : {scene.spp}")
    print(f"  Max depth : {scene.max_depth}")


def cmd_view(args):
    """Render a scene and display progressive updates in the browser."""
    if not os.path.isfile(args.scene):
        print(f"Error: scene file not found: {args.scene}", file=sys.stderr)
        sys.exit(1)
    from .viewer import view
    scene = load_scene(args.scene)
    if args.width:  scene.width  = args.width
    if args.height: scene.height = args.height
    if args.spp:    scene.spp    = args.spp
    port = args.port or 8080
    print(f"Progressive viewer → http://127.0.0.1:{port}/")
    view(scene, workers=args.workers or None, host='127.0.0.1', port=port)


def _default_out(scene_path, ext):
    base = os.path.splitext(os.path.basename(scene_path))[0]
    return f"{base}.{ext}"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Monte Carlo path tracer — pure Python',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # render
    p_render = sub.add_parser('render', help='Render a JSON scene file')
    p_render.add_argument('scene', help='Path to scene JSON')
    p_render.add_argument('-o', '--output', help='Output file path')
    p_render.add_argument('--width',   type=int, help='Override image width')
    p_render.add_argument('--height',  type=int, help='Override image height')
    p_render.add_argument('--spp',     type=int, help='Samples per pixel')
    p_render.add_argument('--depth',   type=int, help='Max path depth')
    p_render.add_argument('--workers', type=int, help='Parallel worker count')
    p_render.add_argument('--format',  choices=['png', 'ppm'], help='Output format')
    p_render.set_defaults(func=cmd_render)

    # demo
    p_demo = sub.add_parser('demo', help='Render all built-in scenes')
    p_demo.add_argument('--width',   type=int, help='Width (default 200)')
    p_demo.add_argument('--height',  type=int, help='Height (default 150)')
    p_demo.add_argument('--spp',     type=int, help='SPP (default 32)')
    p_demo.add_argument('--outdir',  default='renders', help='Output directory')
    p_demo.add_argument('--workers', type=int, help='Parallel workers')
    p_demo.set_defaults(func=cmd_demo)

    # bench
    p_bench = sub.add_parser('bench', help='BVH vs brute-force benchmark')
    p_bench.add_argument('--count',   type=int, default=100, help='Number of spheres')
    p_bench.add_argument('--workers', type=int, default=1)
    p_bench.set_defaults(func=cmd_bench)

    # info
    p_info = sub.add_parser('info', help='Print scene metadata')
    p_info.add_argument('scene', help='Path to scene JSON')
    p_info.set_defaults(func=cmd_info)

    # view — progressive browser viewer
    p_view = sub.add_parser('view', help='Live progressive render in browser (SSE)')
    p_view.add_argument('scene', help='Path to scene JSON')
    p_view.add_argument('--width',   type=int)
    p_view.add_argument('--height',  type=int)
    p_view.add_argument('--spp',     type=int)
    p_view.add_argument('--workers', type=int)
    p_view.add_argument('--port',    type=int, default=8080)
    p_view.set_defaults(func=cmd_view)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
