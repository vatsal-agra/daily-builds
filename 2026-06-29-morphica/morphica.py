#!/usr/bin/env python3
"""
morphica — generative algorithmic art engine

Usage:
  morphica lsystem  <preset>   [options]
  morphica rd        <preset>   [options]
  morphica attractor <name>    [options]
  morphica voronoi             [options]
  morphica stipple             [options]
  morphica viewer              [options]
  morphica demo
  morphica list

Run `morphica <command> --help` for per-command options.
"""
import argparse
import base64
import json
import os
import sys
import time

# Make sure local modules are found
sys.path.insert(0, os.path.dirname(__file__))

from lsystem import PRESETS as LS_PRESETS, render_lsystem
from reactiondiff import PRESETS as RD_PRESETS, simulate, field_to_pixels
from attractors import ATTRACTORS, render_attractor
from voronoi import render_voronoi
from palette import PALETTES, PALETTE_NAMES, sample_palette
from png_encoder import save_png, encode_png


# ── helpers ───────────────────────────────────────────────────────────────────

def _out_path(args, default_name, ext):
    if hasattr(args, "output") and args.output:
        return args.output
    return os.path.join(os.path.dirname(__file__), "output", default_name + ext)


def _ensure_output_dir(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _palette_fn(name):
    def fn(t):
        return sample_palette(name, t)
    return fn


def _save_svg(path, svg_str):
    _ensure_output_dir(path)
    with open(path, "w") as f:
        f.write(svg_str)
    print(f"  Saved SVG → {path}")


def _save_pixels(path, pixels, w, h):
    _ensure_output_dir(path)
    save_png(path, w, h, pixels)
    print(f"  Saved PNG → {path}")


def _pixels_to_b64(pixels, w, h):
    data = encode_png(w, h, pixels)
    return base64.b64encode(data).decode()


# ── lsystem command ───────────────────────────────────────────────────────────

def cmd_lsystem(args):
    preset = args.preset
    if preset not in LS_PRESETS:
        print(f"Error: unknown L-system preset '{preset}'.")
        print(f"Available: {sorted(LS_PRESETS.keys())}")
        sys.exit(1)

    t0 = time.time()
    fmt = args.format if hasattr(args, "format") else "png"
    stroke = args.color if hasattr(args, "color") else "#00CFFF"
    bg = args.bg if hasattr(args, "bg") else "#111111"
    iters = args.iterations if hasattr(args, "iterations") and args.iterations else None
    seed = args.seed if hasattr(args, "seed") else None
    w = getattr(args, "width", 800)
    h = getattr(args, "height", 800)

    if fmt == "svg":
        svg = render_lsystem(preset, iterations=iters, width=w, height=h,
                              output_format="svg", stroke=stroke, bg=bg, seed=seed)
        path = _out_path(args, f"lsystem_{preset}", ".svg")
        _save_svg(path, svg)
    else:
        pixels, pw, ph = render_lsystem(preset, iterations=iters, width=w, height=h,
                                         output_format="pixels", stroke=stroke, bg=bg,
                                         seed=seed)
        path = _out_path(args, f"lsystem_{preset}", ".png")
        _save_pixels(path, pixels, pw, ph)
    print(f"  Done in {time.time()-t0:.2f}s")


# ── reaction-diffusion command ────────────────────────────────────────────────

def cmd_rd(args):
    preset = args.preset
    if preset not in RD_PRESETS:
        print(f"Error: unknown RD preset '{preset}'.")
        print(f"Available: {sorted(RD_PRESETS.keys())}")
        sys.exit(1)

    palette = getattr(args, "palette", "viridis")
    if palette not in PALETTES:
        print(f"Error: unknown palette '{palette}'. Available: {PALETTE_NAMES}")
        sys.exit(1)

    size = getattr(args, "size", 200)
    steps = getattr(args, "steps", 5000)
    seed = getattr(args, "seed", None)

    print(f"  Simulating Gray-Scott '{preset}' ({size}×{size}, {steps} steps)…")
    t0 = time.time()
    flat_v, w, h = simulate(
        preset_name=preset,
        width=size, height=size,
        steps=steps,
        seed=seed,
    )
    print(f"  Simulation done in {time.time()-t0:.2f}s")

    pfn = _palette_fn(palette)
    pixels = field_to_pixels(flat_v, w, h, pfn)

    path = _out_path(args, f"rd_{preset}", ".png")
    _save_pixels(path, pixels, w, h)


# ── attractor command ─────────────────────────────────────────────────────────

def cmd_attractor(args):
    name = args.name
    if name not in ATTRACTORS:
        print(f"Error: unknown attractor '{name}'.")
        print(f"Available: {sorted(ATTRACTORS.keys())}")
        sys.exit(1)

    palette = getattr(args, "palette", "plasma")
    if palette not in PALETTES:
        print(f"Error: unknown palette '{palette}'. Available: {PALETTE_NAMES}")
        sys.exit(1)

    steps = getattr(args, "steps", None)
    seed = getattr(args, "seed", None)
    w = getattr(args, "width", 800)
    h = getattr(args, "height", 800)

    print(f"  Tracing attractor '{name}'…")
    t0 = time.time()
    pixels, pw, ph = render_attractor(
        name,
        width=w, height=h,
        steps=steps,
        seed=seed,
        palette_fn=_palette_fn(palette),
    )
    print(f"  Done in {time.time()-t0:.2f}s")

    path = _out_path(args, f"attractor_{name}", ".png")
    _save_pixels(path, pixels, pw, ph)


# ── voronoi command ───────────────────────────────────────────────────────────

def cmd_voronoi(args):
    n = getattr(args, "points", 80)
    lloyd = getattr(args, "lloyd", 5)
    seed = getattr(args, "seed", None)
    fmt = getattr(args, "format", "svg")
    w = getattr(args, "width", 800)
    h = getattr(args, "height", 800)

    t0 = time.time()
    result = render_voronoi(
        n_points=n, width=w, height=h,
        lloyd_iterations=lloyd, seed=seed,
        output_format="pixels" if fmt == "png" else fmt,
    )
    print(f"  Done in {time.time()-t0:.2f}s")

    if fmt == "svg":
        path = _out_path(args, "voronoi", ".svg")
        _save_svg(path, result)
    else:
        # result is (pixels, w, h) for pixels/png format
        pixels, pw, ph = result
        path = _out_path(args, "voronoi", ".png")
        _save_pixels(path, pixels, pw, ph)


# ── stipple command ───────────────────────────────────────────────────────────

def cmd_stipple(args):
    n = getattr(args, "points", 300)
    lloyd = getattr(args, "lloyd", 5)
    seed = getattr(args, "seed", None)
    w = getattr(args, "width", 800)
    h = getattr(args, "height", 800)

    t0 = time.time()
    pixels, pw, ph = render_voronoi(
        n_points=n, width=w, height=h,
        lloyd_iterations=lloyd, seed=seed,
        output_format="pixels",
        stipple_mode=True,
    )
    print(f"  Done in {time.time()-t0:.2f}s")

    path = _out_path(args, "stipple", ".png")
    _save_pixels(path, pixels, pw, ph)


# ── viewer command ────────────────────────────────────────────────────────────

def cmd_viewer(args):
    import importlib.util
    from viewer import build_viewer
    from lsystem import PRESETS as LSP, rewrite, turtle_to_paths
    import random

    # Pre-render a set of images to embed
    gallery = []
    seed = getattr(args, "seed", 42)

    # L-systems as PNG
    ls_names_gallery = ["koch", "dragon", "barnsley", "hilbert"]
    for i, name in enumerate(ls_names_gallery):
        print(f"  [{i+1}/{len(ls_names_gallery)}] L-system: {name}…")
        pixels, w, h = render_lsystem(name, width=400, height=400,
                                       output_format="pixels", seed=seed)
        b64 = _pixels_to_b64(pixels, w, h)
        gallery.append({
            "title": f"L-System: {name}",
            "desc": LSP[name].get("description", name),
            "b64": b64,
            "key": name,
        })

    # Attractors
    att_gallery = ["clifford", "dejong", "lorenz"]
    for i, aname in enumerate(att_gallery):
        print(f"  [{i+1}/{len(att_gallery)}] Attractor: {aname}…")
        pixels, w, h = render_attractor(aname, width=400, height=400,
                                         seed=seed, palette_fn=_palette_fn("plasma"))
        b64 = _pixels_to_b64(pixels, w, h)
        gallery.append({
            "title": f"Attractor: {aname}",
            "desc": ATTRACTORS[aname]["description"],
            "b64": b64,
            "key": aname,
        })

    # RD — one preset
    print("  Reaction-diffusion: worms (200×200, 3000 steps)…")
    flat_v, rdw, rdh = simulate(preset_name="worms", width=200, height=200,
                                 steps=3000, seed=seed)
    px = field_to_pixels(flat_v, rdw, rdh, _palette_fn("viridis"))
    b64 = _pixels_to_b64(px, rdw, rdh)
    gallery.append({
        "title": "Reaction-Diffusion: worms",
        "desc": RD_PRESETS["worms"]["description"],
        "b64": b64,
        "key": "worms",
    })

    # Voronoi
    print("  Voronoi: 60 points…")
    voronoi_px, vw, vh = render_voronoi(
        n_points=60, width=400, height=400, lloyd_iterations=4,
        seed=seed, output_format="pixels"
    )
    b64 = _pixels_to_b64(voronoi_px, vw, vh)
    gallery.append({
        "title": "Voronoi (Lloyd relaxed)",
        "desc": "60-site centroidal Voronoi tessellation",
        "b64": b64,
        "key": "voronoi",
    })

    # Build JS L-system data (axiom + rules + angle)
    ls_data = {}
    for name, cfg in LSP.items():
        rules = {}
        for k, v in cfg["rules"].items():
            if isinstance(v, list):  # stochastic → take first production
                rules[k] = v[0][1]
            else:
                rules[k] = v
        ls_data[name] = {
            "axiom": cfg["axiom"],
            "rules": rules,
            "angle_deg": cfg["angle"],
        }

    html = build_viewer(
        gallery_items=gallery,
        lsystem_data=ls_data,
        attractor_names=sorted(ATTRACTORS.keys()),
        ls_names=sorted(LSP.keys()),
    )

    path = _out_path(args, "viewer", ".html")
    _ensure_output_dir(path)
    with open(path, "w") as f:
        f.write(html)
    print(f"  Viewer → {path}")
    print("  Open in a browser to explore.")


# ── animate command ───────────────────────────────────────────────────────────

def cmd_animate(args):
    from animate import animate_lsystem, animate_rd, animate_attractor

    atype = args.type
    name = args.name
    n_frames = args.frames
    seed = args.seed
    w = args.width
    h = args.height
    palette = args.palette
    out_dir = args.output or os.path.join(os.path.dirname(__file__), "output", f"anim_{atype}_{name}")

    print(f"  Animating {atype} '{name}' → {n_frames} frames in {out_dir}")
    t0 = time.time()

    if atype == "lsystem":
        files = animate_lsystem(
            name, max_iter=n_frames - 1, width=w, height=h,
            output_dir=out_dir, seed=seed,
        )
    elif atype == "rd":
        files = animate_rd(
            name, n_frames=n_frames, width=min(w, 200), height=min(h, 200),
            palette_name=palette, output_dir=out_dir, seed=seed,
        )
    elif atype == "attractor":
        files = animate_attractor(
            name, n_frames=n_frames, width=w, height=h,
            palette_name=palette, output_dir=out_dir, seed=seed,
        )
    else:
        print(f"Unknown animation type '{atype}'")
        sys.exit(1)

    print(f"  {len(files)} frames written in {time.time()-t0:.2f}s")
    print(f"  To make a GIF: convert -delay 10 {out_dir}/frame_*.png animation.gif")


# ── demo command ──────────────────────────────────────────────────────────────

def cmd_demo(args):
    """Run a quick smoke-test of all features."""
    print("\n── Morphica Demo ──────────────────────────────────────────────────")
    base = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(base, exist_ok=True)

    class FakeArgs:
        output = None; seed = 42; width = 400; height = 400
        format = "png"; color = "#00CFFF"; bg = "#111111"
        iterations = None; palette = "viridis"; size = 100; steps = 1000
        points = 40; lloyd = 3

    a = FakeArgs()

    print("\n[1/6] L-System: hilbert")
    a.preset = "hilbert"; a.output = os.path.join(base, "demo_lsystem.png")
    cmd_lsystem(a)

    print("\n[2/6] L-System SVG: koch")
    a.preset = "koch"; a.format = "svg"; a.output = os.path.join(base, "demo_lsystem.svg")
    cmd_lsystem(a)
    a.format = "png"

    print("\n[3/6] Reaction-diffusion: worms (100×100, 1000 steps)")
    a.preset = "worms"; a.output = os.path.join(base, "demo_rd.png")
    cmd_rd(a)

    print("\n[4/6] Attractor: clifford")
    a.name = "clifford"; a.palette = "plasma"
    a.output = os.path.join(base, "demo_attractor.png")
    cmd_attractor(a)

    print("\n[5/6] Voronoi: 40 points, 3 Lloyd iters")
    a.output = os.path.join(base, "demo_voronoi.png"); a.format = "png"
    cmd_voronoi(a)

    print("\n[6/6] Viewer HTML")
    a.output = os.path.join(base, "demo_viewer.html")
    cmd_viewer(a)

    print("\n── All demos complete ─────────────────────────────────────────────")


# ── list command ──────────────────────────────────────────────────────────────

def cmd_list(args):
    print("\nL-system presets:")
    for name, cfg in sorted(LS_PRESETS.items()):
        print(f"  {name:20s}  {cfg.get('description','')}")
    print("\nReaction-diffusion presets:")
    for name, cfg in sorted(RD_PRESETS.items()):
        print(f"  {name:20s}  {cfg.get('description','')}")
    print("\nAttractors:")
    for name, cfg in sorted(ATTRACTORS.items()):
        print(f"  {name:20s}  {cfg.get('description','')}")
    print("\nPalettes:")
    print(" ", ", ".join(PALETTE_NAMES))


# ── argument parser ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        prog="morphica",
        description="Generative algorithmic art engine",
    )
    sub = p.add_subparsers(dest="command", metavar="command")

    # lsystem
    ls = sub.add_parser("lsystem", help="Render an L-system")
    ls.add_argument("preset", help=f"Preset name. Run 'list' to see all.")
    ls.add_argument("-n", "--iterations", type=int, default=None)
    ls.add_argument("--width", type=int, default=800)
    ls.add_argument("--height", type=int, default=800)
    ls.add_argument("--color", default="#00CFFF", help="Stroke colour hex")
    ls.add_argument("--bg", default="#111111", help="Background colour hex")
    ls.add_argument("--format", choices=["png","svg"], default="png")
    ls.add_argument("--seed", type=int, default=None)
    ls.add_argument("-o", "--output", default=None)

    # rd
    rd = sub.add_parser("rd", help="Run Gray-Scott reaction-diffusion")
    rd.add_argument("preset", help="Preset name")
    rd.add_argument("--size", type=int, default=200, help="Grid size (NxN)")
    rd.add_argument("--steps", type=int, default=5000)
    rd.add_argument("--palette", default="viridis", choices=PALETTE_NAMES)
    rd.add_argument("--seed", type=int, default=None)
    rd.add_argument("-o", "--output", default=None)

    # attractor
    att = sub.add_parser("attractor", help="Render a strange attractor")
    att.add_argument("name", help="Attractor name")
    att.add_argument("--width", type=int, default=800)
    att.add_argument("--height", type=int, default=800)
    att.add_argument("--steps", type=int, default=None)
    att.add_argument("--palette", default="plasma", choices=PALETTE_NAMES)
    att.add_argument("--seed", type=int, default=None)
    att.add_argument("-o", "--output", default=None)

    # voronoi
    vor = sub.add_parser("voronoi", help="Render a Voronoi diagram")
    vor.add_argument("--points", type=int, default=80, metavar="N",
                     help="Number of Voronoi sites (≥1)")
    vor.add_argument("--width", type=int, default=800)
    vor.add_argument("--height", type=int, default=800)
    vor.add_argument("--lloyd", type=int, default=5)
    vor.add_argument("--format", choices=["png","svg"], default="svg")
    vor.add_argument("--seed", type=int, default=None)
    vor.add_argument("-o", "--output", default=None)

    # stipple
    stp = sub.add_parser("stipple", help="Render weighted stipple art")
    stp.add_argument("--points", type=int, default=300)
    stp.add_argument("--width", type=int, default=800)
    stp.add_argument("--height", type=int, default=800)
    stp.add_argument("--lloyd", type=int, default=5)
    stp.add_argument("--seed", type=int, default=None)
    stp.add_argument("-o", "--output", default=None)

    # viewer
    vie = sub.add_parser("viewer", help="Build interactive HTML viewer")
    vie.add_argument("--seed", type=int, default=42)
    vie.add_argument("-o", "--output", default=None)

    # animate
    ani = sub.add_parser("animate", help="Export animation frames as PNG sequence")
    ani.add_argument("type", choices=["lsystem", "rd", "attractor"],
                     help="What to animate")
    ani.add_argument("name", help="Preset or attractor name")
    ani.add_argument("--frames", type=int, default=10, help="Number of output frames")
    ani.add_argument("--width", type=int, default=600)
    ani.add_argument("--height", type=int, default=600)
    ani.add_argument("--palette", default="plasma", choices=PALETTE_NAMES)
    ani.add_argument("--seed", type=int, default=None)
    ani.add_argument("-o", "--output", default=None,
                     help="Output directory for frames")

    # demo
    sub.add_parser("demo", help="Run all features end-to-end")

    # list
    sub.add_parser("list", help="List all presets/attractors/palettes")

    args = p.parse_args()

    dispatch = {
        "lsystem":   cmd_lsystem,
        "rd":        cmd_rd,
        "attractor": cmd_attractor,
        "voronoi":   cmd_voronoi,
        "stipple":   cmd_stipple,
        "viewer":    cmd_viewer,
        "animate":   cmd_animate,
        "demo":      cmd_demo,
        "list":      cmd_list,
    }

    if args.command is None:
        p.print_help()
        sys.exit(0)

    fn = dispatch.get(args.command)
    if fn is None:
        p.print_help()
        sys.exit(1)

    fn(args)


if __name__ == "__main__":
    main()
