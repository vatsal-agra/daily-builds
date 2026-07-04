#!/usr/bin/env python3
"""
Flux — 2D Navier-Stokes Fluid Simulation CLI

Commands:
  render   Render a scene to PNG frames or a single PNG
  anim     Render a scene to an HTML animation gallery
  demo     Render all built-in scenes + produce an HTML gallery
  info     Print scene/solver parameters without rendering
"""

import argparse
import os
import sys
import time
import base64
import json

from fluid import FluidGrid
from render import render_frame, encode_png, RENDER_MODES
from scenes import SCENES, load_json_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_scene(scene_arg: str, N: int):
    if scene_arg.endswith(".json") and os.path.isfile(scene_arg):
        return load_json_scene(scene_arg)
    if scene_arg in SCENES:
        return SCENES[scene_arg](N)
    print(f"Unknown scene '{scene_arg}'. Available: {', '.join(SCENES)}", file=sys.stderr)
    sys.exit(1)


def _progress(frame: int, total: int, start: float, prefix: str = "") -> None:
    pct = frame / total * 100
    elapsed = time.time() - start
    fps = frame / elapsed if elapsed > 0 else 0
    bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
    print(f"\r{prefix}[{bar}] {pct:5.1f}%  frame {frame:4d}/{total}  {fps:.1f} fps",
          end="", flush=True)


def _run_simulation(fluid, inject_fn, meta,
                    skip: int = 0, frames: int = None,
                    mode: str = "composite", scale: int = 4,
                    verbose: bool = True):
    """Run the simulation for `frames` steps, yielding (frame, rgb_array) pairs."""
    total = frames if frames is not None else meta["frames"]
    start = time.time()

    # Pre-warm (run skip frames without yielding)
    for i in range(skip):
        inject_fn(fluid.frame)
        fluid.step()
        if verbose:
            _progress(i + 1, skip + total, start, prefix="pre-warm ")

    for i in range(total):
        inject_fn(fluid.frame)
        fluid.step()
        rgb = render_frame(fluid, mode=mode, scale=scale)
        if verbose:
            _progress(skip + i + 1, skip + total, start)
        yield i, rgb

    if verbose:
        elapsed = time.time() - start
        print(f"\nDone in {elapsed:.1f}s  ({(skip + total) / elapsed:.1f} fps)")


# ---------------------------------------------------------------------------
# HTML animation builder
# ---------------------------------------------------------------------------

def _build_html_anim(frames_b64: list, meta: dict, mode: str,
                     frame_ms: int = 50) -> str:
    imgs_js = "[\n" + ",\n".join(
        f'  "data:image/png;base64,{b64}"' for b64 in frames_b64
    ) + "\n]"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Flux — {meta['name']}</title>
<style>
  body {{ background:#0d0d0d; color:#ccc; font-family:monospace;
          display:flex; flex-direction:column; align-items:center;
          padding:20px; margin:0; }}
  h1   {{ color:#ff9040; margin:0 0 6px; font-size:1.4em; }}
  p    {{ margin:0 0 16px; color:#888; font-size:.85em; }}
  canvas {{ border:1px solid #333; image-rendering:pixelated; }}
  .controls {{ margin-top:12px; display:flex; gap:12px; align-items:center; }}
  button {{ background:#222; color:#ccc; border:1px solid #444;
             padding:6px 14px; cursor:pointer; border-radius:4px; font-family:monospace; }}
  button:hover {{ background:#333; }}
  .info {{ color:#666; font-size:.75em; margin-top:8px; }}
</style>
</head>
<body>
<h1>Flux / {meta['name']}</h1>
<p>{meta.get('description','')}</p>
<canvas id="c"></canvas>
<div class="controls">
  <button id="btn-play">⏸ Pause</button>
  <button id="btn-restart">↺ Restart</button>
  <span class="info" id="info"></span>
</div>
<script>
const FRAMES = {imgs_js};
const DELAY  = {frame_ms};
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
const info   = document.getElementById('info');
const btnPlay = document.getElementById('btn-play');
let idx = 0, playing = true, timer = null;
const imgs = FRAMES.map(src => {{ const i = new Image(); i.src = src; return i; }});
imgs[0].onload = () => {{
  canvas.width  = imgs[0].naturalWidth;
  canvas.height = imgs[0].naturalHeight;
}};
function draw() {{
  if (!imgs[idx].complete) return;
  ctx.drawImage(imgs[idx], 0, 0);
  info.textContent = 'frame ' + (idx+1) + ' / ' + FRAMES.length + '  |  mode: {mode}';
  idx = (idx + 1) % FRAMES.length;
}}
function start() {{ if (!timer) timer = setInterval(draw, DELAY); }}
function stop()  {{ clearInterval(timer); timer = null; }}
start();
btnPlay.addEventListener('click', () => {{
  playing = !playing;
  btnPlay.textContent = playing ? '⏸ Pause' : '▶ Play';
  playing ? start() : stop();
}});
document.getElementById('btn-restart').addEventListener('click', () => {{ idx = 0; }});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_render(args):
    fluid, inject_fn, meta = _get_scene(args.scene, args.N)
    os.makedirs(args.output, exist_ok=True)
    n_frames = args.frames or meta["frames"]

    for i, rgb in _run_simulation(fluid, inject_fn, meta,
                                   skip=args.skip, frames=n_frames,
                                   mode=args.mode, scale=args.scale):
        path = os.path.join(args.output, f"frame_{i:04d}.png")
        with open(path, "wb") as f:
            f.write(encode_png(rgb))

    print(f"Wrote {n_frames} frames to {args.output}/")


def cmd_anim(args):
    fluid, inject_fn, meta = _get_scene(args.scene, args.N)
    n_frames = args.frames or meta["frames"]
    frames_b64 = []

    for i, rgb in _run_simulation(fluid, inject_fn, meta,
                                   skip=args.skip, frames=n_frames,
                                   mode=args.mode, scale=args.scale):
        png = encode_png(rgb)
        frames_b64.append(base64.b64encode(png).decode())

    html = _build_html_anim(frames_b64, meta, args.mode,
                             frame_ms=args.frame_ms)
    out = args.output or f"{meta['name']}_anim.html"
    with open(out, "w") as f:
        f.write(html)
    print(f"Animation saved to {out}  ({n_frames} frames, {len(html)//1024} KB)")


def cmd_demo(args):
    """Render all scenes and write a single HTML gallery."""
    os.makedirs(args.output or "demo_output", exist_ok=True)
    out_dir = args.output or "demo_output"
    scene_htmls = {}

    for name, fn in SCENES.items():
        print(f"\n=== Scene: {name} ===")
        fluid, inject_fn, meta = fn(args.N)
        n_frames = min(args.frames, meta["frames"])
        frames_b64 = []

        for _, rgb in _run_simulation(fluid, inject_fn, meta,
                                       skip=0, frames=n_frames,
                                       mode=args.mode, scale=args.scale):
            png = encode_png(rgb)
            frames_b64.append(base64.b64encode(png).decode())

        html = _build_html_anim(frames_b64, meta, args.mode, frame_ms=50)
        path = os.path.join(out_dir, f"{name}.html")
        with open(path, "w") as f:
            f.write(html)
        scene_htmls[name] = os.path.basename(path)
        print(f"  → {path}")

    # Write an index
    links = "\n".join(
        f'<li><a href="{v}">{k}</a></li>' for k, v in scene_htmls.items()
    )
    index = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>Flux Demo Gallery</title>
<style>body{{background:#0d0d0d;color:#ccc;font-family:monospace;padding:30px;}}
a{{color:#ff9040;}} li{{margin:6px 0;font-size:1.1em;}}</style>
</head><body>
<h1 style="color:#ff9040">Flux — Demo Gallery</h1>
<p>All built-in scenes rendered at N={args.N}</p>
<ul>{links}</ul>
</body></html>"""
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w") as f:
        f.write(index)
    print(f"\nGallery index: {index_path}")


def cmd_info(args):
    if args.scene.endswith(".json") and os.path.isfile(args.scene):
        fluid, _, meta = load_json_scene(args.scene)
        print(f"JSON scene: {args.scene}")
    elif args.scene in SCENES:
        fluid, _, meta = SCENES[args.scene](args.N)
        print(f"Built-in scene: {args.scene}")
    else:
        print(f"Unknown scene '{args.scene}'", file=sys.stderr)
        sys.exit(1)

    print(f"  Name:        {meta['name']}")
    print(f"  Description: {meta['description']}")
    print(f"  Frames:      {meta['frames']}")
    print(f"  Grid:        {fluid.N}×{fluid.N}  ({(fluid.N+2)**2} cells)")
    print(f"  dt:          {fluid.dt}")
    print(f"  viscosity:   {fluid.visc}")
    print(f"  diffusion:   {fluid.diff}")
    print(f"  vort_scale:  {fluid.vort_scale}")
    print(f"  gravity:     {fluid.gravity}")
    print(f"  dye channels:{len(fluid.dyes)}")
    print(f"  obstacles:   {fluid.obstacles.sum()} cells solid")
    print(f"  render modes:{', '.join(RENDER_MODES)}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flux",
        description="Flux — 2D Navier-Stokes Fluid Simulation",
    )
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--scene",  default="smoke",
                        help="scene name or path to .json (default: smoke)")
    common.add_argument("--N",      type=int, default=64,
                        help="grid resolution (default: 64)")
    common.add_argument("--frames", type=int, default=0,
                        help="number of frames (0=scene default)")
    common.add_argument("--skip",   type=int, default=0,
                        help="pre-warm frames to skip before rendering")
    common.add_argument("--mode",   default="composite",
                        choices=list(RENDER_MODES.keys()),
                        help="render mode (default: composite)")
    common.add_argument("--scale",  type=int, default=4,
                        help="pixel scale factor (default: 4)")

    # render
    r = sub.add_parser("render", parents=[common],
                       help="Render frames as individual PNG files")
    r.add_argument("--output", default="frames",
                   help="output directory (default: frames/)")

    # anim
    a = sub.add_parser("anim", parents=[common],
                       help="Render an HTML animation file")
    a.add_argument("--output",   default="",
                   help="output HTML path (default: <scene>_anim.html)")
    a.add_argument("--frame-ms", type=int, default=50, dest="frame_ms",
                   help="ms per frame in animation (default: 50)")

    # demo
    d = sub.add_parser("demo", parents=[common],
                       help="Render all scenes to an HTML gallery")
    d.add_argument("--output", default="demo_output",
                   help="output directory (default: demo_output/)")
    d.set_defaults(frames=60)  # quick render for demo

    # info
    i = sub.add_parser("info", help="Print scene info without rendering")
    i.add_argument("--scene", default="smoke")
    i.add_argument("--N",     type=int, default=64)

    return p


def main():
    p = build_parser()
    args = p.parse_args()
    if args.command == "render":
        cmd_render(args)
    elif args.command == "anim":
        cmd_anim(args)
    elif args.command == "demo":
        cmd_demo(args)
    elif args.command == "info":
        cmd_info(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
