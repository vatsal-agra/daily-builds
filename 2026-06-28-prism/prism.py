#!/usr/bin/env python3
"""
Prism — Software 3D Rasterizer
CLI entry point.

Subcommands:
  render    Render a named scene to PNG
  animate   Render N rotation frames to an animated HTML viewer
  obj       Load and render a Wavefront OBJ file
  shadows   Render shadow-map demo scene
  compare   Side-by-side flat/Gouraud/Phong/wireframe comparison
  info      Print pipeline info / scene stats
  demo      Run full demo (all scenes, writes output/ directory)
"""
import sys
import os
import math
import time
import argparse

# Allow running as: python prism.py <cmd> from the project root
sys.path.insert(0, os.path.dirname(__file__))

from src.math3d import Vec3, Mat4
from src.framebuffer import Framebuffer, DepthBuffer
from src.camera import Camera, LightCamera
from src.geometry import Material, Mesh, make_scene_objects, load_obj
from src.rasterizer import RenderContext, render_mesh, render_depth
from src.shader import Light
from src.texture import checkerboard, marble, earth_like, uv_grid, gradient
from src.png_encoder import encode_png, save_png
from src.html_viewer import build_html_viewer, build_comparison_html


# ── Helpers ──

def _out_dir(base="output"):
    d = os.path.join(os.path.dirname(__file__), base)
    os.makedirs(d, exist_ok=True)
    return d


def _make_camera(scene_name, width, height):
    aspect = width/height
    presets = {
        "torus":      dict(eye=Vec3(0,1.8,4), center=Vec3(0,0,0), fov_y=40),
        "sphere":     dict(eye=Vec3(0,0,3),   center=Vec3(0,0,0), fov_y=45),
        "cornell":    dict(eye=Vec3(0,2,5),   center=Vec3(0,2,0), fov_y=42),
        "shadow_demo":dict(eye=Vec3(3,4,5),   center=Vec3(0,-0.5,0), fov_y=40),
        "showcase":   dict(eye=Vec3(0,2.5,7), center=Vec3(0,0,0), fov_y=42),
    }
    p = presets.get(scene_name, dict(eye=Vec3(0,2,5),center=Vec3(0,0,0),fov_y=45))
    return Camera(eye=p['eye'], center=p['center'], fov_y=p['fov_y'],
                  aspect=aspect, near=0.1, far=200.0, width=width, height=height)


def _default_lights(scene_name, view_matrix):
    """Return list of Lights already transformed to view/camera space."""
    if scene_name == "cornell":
        world_lights = [
            Light.ambient(Vec3(0.5,0.45,0.4), intensity=0.45),
            # Ceiling area light (main)
            Light.point(Vec3(0, 3.8, -0.5), Vec3(1.0, 0.97, 0.88), intensity=16.0),
            # Front fill so camera-facing surfaces aren't pitch black
            Light.point(Vec3(0, 2.0, 6.0), Vec3(0.9, 0.92, 1.0), intensity=10.0),
        ]
    elif scene_name == "shadow_demo":
        world_lights = [
            Light.ambient(Vec3(0.6,0.7,0.9), intensity=0.25),
            Light.point(Vec3(3, 6, 4), Vec3(1.0, 0.98, 0.90), intensity=12.0),
            Light.point(Vec3(-2, 3, 2), Vec3(0.6, 0.7, 1.0), intensity=3.0),
        ]
    elif scene_name == "showcase":
        world_lights = [
            Light.ambient(Vec3(0.7,0.7,0.9), intensity=0.2),
            Light.point(Vec3(5, 8, 5), Vec3(1.0, 0.96, 0.85), intensity=10.0),
            Light.point(Vec3(-4, 4, 3), Vec3(0.5, 0.6, 1.0), intensity=4.0),
        ]
    else:
        world_lights = [
            Light.ambient(Vec3(0.6,0.65,0.7), intensity=0.2),
            Light.point(Vec3(3, 5, 3), Vec3(1.0, 0.97, 0.85), intensity=8.0),
            Light.point(Vec3(-2, 3, 1), Vec3(0.5, 0.6, 1.0), intensity=3.0),
        ]
    # Transform light positions/directions to view space
    view_lights = []
    for lt in world_lights:
        if lt.kind == 'ambient':
            view_lights.append(lt)
        elif lt.kind == 'directional':
            vdir = view_matrix.transform_direction(lt.pos_or_dir)
            view_lights.append(Light(vdir, lt.color, lt.intensity, 'directional'))
        else:
            vpos = view_matrix.transform_point(lt.pos_or_dir)
            view_lights.append(Light(vpos, lt.color, lt.intensity, 'point',
                                     lt.attenuation))
    return view_lights


def _build_textures():
    return {
        'checker': checkerboard(128, 128, (0.9,0.9,0.9), (0.1,0.1,0.1), tiles=8),
        'marble':  marble(128, 128),
        'earth':   earth_like(128, 128),
        'uvgrid':  uv_grid(128, 128),
        'grad':    gradient(128, 128),
    }


def _render_scene(scene_name, width, height, msaa=1,
                  shadow=False, wireframe=False, rotation_y=0.0,
                  textures=None):
    """Core render: returns (Framebuffer, elapsed_seconds)."""
    t0 = time.time()
    if textures is None:
        textures = _build_textures()
    fb = Framebuffer(width, height, msaa=msaa)
    # Background color (sky gradient approximation)
    fb.clear((0.05, 0.06, 0.14))

    cam = _make_camera(scene_name, width, height)
    lights = _default_lights(scene_name, cam.view_matrix)

    objects = make_scene_objects(scene_name, textures)

    # Optionally rotate the whole scene around Y
    rot = Mat4.rotation_y(rotation_y) if rotation_y != 0.0 else Mat4.identity()

    # Shadow map pass
    smap = None
    light_vp = None
    if shadow:
        smap, light_vp = _render_shadow_pass(scene_name, objects, rot, width, height)

    # Build lights in view space (already done above)
    ctx = RenderContext(fb, cam, lights, shadow_map=smap, light_vp=light_vp,
                        wireframe=wireframe)

    for mesh, model_mat in objects:
        render_mesh(ctx, mesh, rot * model_mat)

    return fb, time.time() - t0


def _render_shadow_pass(scene_name, objects, rot, width, height):
    """Render depth from light, return (DepthBuffer, light_vp_matrix)."""
    # Determine light position
    light_presets = {
        "shadow_demo": Vec3(3, 6, 4),
        "showcase":    Vec3(5, 8, 5),
    }
    lpos = light_presets.get(scene_name, Vec3(3, 5, 3))
    lcenter = Vec3(0, 0, 0)
    lcam = LightCamera(eye=lpos, center=lcenter, ortho=True, ortho_size=5.0,
                       near=0.5, far=30.0, width=width, height=height)
    light_vp = lcam.proj_matrix * lcam.view_matrix
    smap = DepthBuffer(width, height)
    smap.clear()
    for mesh, model_mat in objects:
        render_depth(smap, mesh, rot * model_mat, lcam)
    return smap, light_vp


def _fb_to_png(fb, gamma=2.2):
    rgb = fb.resolve_to_rgb_bytes(gamma=gamma)
    return encode_png(fb.width, fb.height, rgb)


# ── Subcommands ──

def cmd_render(args):
    scene = args.scene or "torus"
    w, h = args.width, args.height
    msaa = args.msaa
    shadow = args.shadow

    print(f"Rendering '{scene}' at {w}×{h} (MSAA={msaa}×, shadow={shadow})…", flush=True)
    textures = _build_textures()
    fb, elapsed = _render_scene(scene, w, h, msaa=msaa, shadow=shadow,
                                textures=textures)
    out = _out_dir()
    fname = f"{scene}{'_shadow' if shadow else ''}.png"
    path = os.path.join(out, fname)
    save_png(path, fb.width, fb.height, fb.resolve_to_rgb_bytes())
    print(f"  → {path}  ({elapsed:.2f}s, {len(fb.triangles_rendered) if hasattr(fb,'triangles_rendered') else '—'} triangles)")


def cmd_animate(args):
    scene = args.scene or "torus"
    w, h = args.width, args.height
    n_frames = args.frames
    shadow = args.shadow
    msaa = args.msaa

    print(f"Animating '{scene}' ({n_frames} frames at {w}×{h}, MSAA={msaa}×)…", flush=True)
    textures = _build_textures()
    frames_png = []
    for i in range(n_frames):
        angle = 2*math.pi*i/n_frames
        fb, elapsed = _render_scene(scene, w, h, msaa=msaa, shadow=shadow,
                                    rotation_y=angle, textures=textures)
        png = _fb_to_png(fb)
        frames_png.append(png)
        print(f"  frame {i+1}/{n_frames} ({elapsed:.2f}s)", flush=True)

    html = build_html_viewer(frames_png, title=f"Prism — {scene.title()}",
                             fps=args.fps, width=w, height=h,
                             caption=f"Scene: {scene} · {n_frames} frames · MSAA {msaa}×")
    out = _out_dir()
    path = os.path.join(out, f"{scene}_anim.html")
    with open(path, 'w') as f: f.write(html)
    print(f"  → {path}")


def cmd_obj(args):
    if not args.file:
        print("Error: --file required for obj subcommand", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file!r}", file=sys.stderr)
        sys.exit(1)

    w, h = args.width, args.height
    msaa = args.msaa
    print(f"Loading OBJ: {args.file!r} …", flush=True)
    try:
        mesh = load_obj(args.file)
    except Exception as e:
        print(f"Error loading OBJ: {e}", file=sys.stderr); sys.exit(1)

    n_tris = len(mesh.triangles)
    print(f"  Loaded {n_tris} triangles")
    if n_tris == 0:
        print("Warning: no triangles found in OBJ"); sys.exit(0)

    textures = _build_textures()
    fb = Framebuffer(w, h, msaa=msaa)
    fb.clear((0.07, 0.07, 0.12))
    cam = Camera(eye=Vec3(0, 1, 4), center=Vec3(0, 0, 0), fov_y=45,
                 aspect=w/h, near=0.01, far=200, width=w, height=h)
    lights = _default_lights("obj", cam.view_matrix)
    rot = Mat4.rotation_y(args.rotate or 0.0)
    ctx = RenderContext(fb, cam, lights, wireframe=args.wireframe)
    t0 = time.time()
    render_mesh(ctx, mesh, rot)
    elapsed = time.time() - t0

    out = _out_dir()
    bname = os.path.splitext(os.path.basename(args.file))[0]
    path = os.path.join(out, f"{bname}.png")
    save_png(path, fb.width, fb.height, fb.resolve_to_rgb_bytes())
    print(f"  → {path}  ({elapsed:.2f}s)")

    if args.animate:
        n_frames = args.frames
        print(f"Animating OBJ ({n_frames} frames)…", flush=True)
        frames_png = []
        for i in range(n_frames):
            angle = 2*math.pi*i/n_frames
            fb2 = Framebuffer(w, h, msaa=msaa)
            fb2.clear((0.07, 0.07, 0.12))
            ctx2 = RenderContext(fb2, cam, lights, wireframe=args.wireframe)
            render_mesh(ctx2, mesh, Mat4.rotation_y(angle))
            frames_png.append(_fb_to_png(fb2))
            print(f"  frame {i+1}/{n_frames}", flush=True)
        html = build_html_viewer(frames_png, title=f"Prism — {bname}",
                                 width=w, height=h)
        hpath = os.path.join(out, f"{bname}_anim.html")
        with open(hpath, 'w') as f: f.write(html)
        print(f"  → {hpath}")


def cmd_shadows(args):
    w, h = args.width, args.height
    msaa = args.msaa
    print(f"Shadow mapping demo at {w}×{h} (MSAA={msaa}×)…", flush=True)
    textures = _build_textures()

    frames = []
    for shadow in [False, True]:
        fb, elapsed = _render_scene("shadow_demo", w, h, msaa=msaa,
                                    shadow=shadow, textures=textures)
        frames.append({
            'label': "With shadow mapping" if shadow else "No shadows",
            'png_bytes': _fb_to_png(fb),
            'caption': f"PCF 3×3 shadow map, {elapsed:.2f}s" if shadow else f"{elapsed:.2f}s",
        })
        print(f"  {'shadow' if shadow else 'no-shadow'}: {elapsed:.2f}s", flush=True)

    out = _out_dir()
    html = build_comparison_html(frames, title="Prism — Shadow Mapping Demo")
    path = os.path.join(out, "shadow_compare.html")
    with open(path, 'w') as f: f.write(html)
    print(f"  → {path}")

    # Also save individual PNGs
    for i, info in enumerate(frames):
        p = os.path.join(out, f"shadow_{'on' if i else 'off'}.png")
        with open(p, 'wb') as f: f.write(info['png_bytes'])
    print(f"  → {out}/shadow_on.png + shadow_off.png")


def cmd_compare(args):
    """Flat / Gouraud(Phong) / Wireframe / Textured comparison."""
    scene = args.scene or "torus"
    w, h = args.width, args.height
    print(f"Rendering comparison for '{scene}' at {w}×{h}…", flush=True)
    textures = _build_textures()

    renders = []

    # 1. Wireframe
    fb, el = _render_scene(scene, w, h, wireframe=True, textures=textures)
    renders.append({'label':'Wireframe','png_bytes':_fb_to_png(fb),'caption':f'{el:.2f}s'})
    print(f"  wireframe: {el:.2f}s", flush=True)

    # 2. Phong shading (no texture)
    fb, el = _render_scene(scene, w, h, textures={})
    renders.append({'label':'Phong (no texture)','png_bytes':_fb_to_png(fb),'caption':f'{el:.2f}s'})
    print(f"  phong: {el:.2f}s", flush=True)

    # 3. With texture
    fb, el = _render_scene(scene, w, h, textures=textures)
    renders.append({'label':'Phong + Texture','png_bytes':_fb_to_png(fb),'caption':f'{el:.2f}s'})
    print(f"  textured: {el:.2f}s", flush=True)

    # 4. MSAA 2×
    fb, el = _render_scene(scene, w, h, msaa=2, textures=textures)
    renders.append({'label':'MSAA 2×','png_bytes':_fb_to_png(fb),'caption':f'{el:.2f}s'})
    print(f"  msaa2x: {el:.2f}s", flush=True)

    out = _out_dir()
    html = build_comparison_html(renders, title=f"Prism — {scene.title()} Comparison")
    path = os.path.join(out, f"{scene}_compare.html")
    with open(path, 'w') as f: f.write(html)
    print(f"  → {path}")


def cmd_info(args):
    """Print pipeline info."""
    from src.geometry import _make_torus, _make_sphere, _make_cube, _make_cylinder
    print("Prism — Software 3D Rasterizer")
    print("=" * 40)
    print(f"  Framebuffer: float RGB + float depth per pixel")
    print(f"  Rasterizer:  edge functions, barycentric interp, z-buffer, top-left fill rule")
    print(f"  Shading:     Blinn-Phong (ambient + diffuse + specular)")
    print(f"  Texturing:   perspective-correct UV, bilinear filtering")
    print(f"  Shadows:     PCF 3×3 shadow mapping")
    print(f"  Anti-alias:  MSAA 2× (4 samples, box resolve)")
    print(f"  Output:      PNG (from-scratch encoder) + HTML flipbook viewer")
    print()
    models = [
        ("torus",    _make_torus()),
        ("sphere",   _make_sphere()),
        ("cube",     _make_cube()),
        ("cylinder", _make_cylinder()),
    ]
    print("Built-in procedural models:")
    for name, m in models:
        print(f"  {name:12s} {len(m.triangles):4d} triangles")
    print()
    print("Scenes: torus, sphere, cornell, shadow_demo, showcase")


def cmd_demo(args):
    w, h = args.width, args.height
    msaa = args.msaa
    print("Prism — Full Demo")
    print("=" * 50)
    out = _out_dir()
    textures = _build_textures()

    # D1: Torus rotation animation
    print("\n[D1] Torus rotation animation…", flush=True)
    n = args.frames
    frames = []
    for i in range(n):
        angle = 2*math.pi*i/n
        fb, el = _render_scene("torus", w, h, msaa=msaa, rotation_y=angle,
                               textures=textures)
        frames.append(_fb_to_png(fb))
        print(f"  frame {i+1}/{n} ({el:.2f}s)", flush=True)
    html = build_html_viewer(frames, title="Prism — Torus", fps=args.fps,
                             width=w, height=h,
                             caption="Gold torus · Blinn-Phong · 2 lights · 3200 triangles")
    with open(os.path.join(out, "torus_anim.html"), 'w') as f: f.write(html)
    save_png(os.path.join(out, "torus.png"), w, h,
             Framebuffer(w,h).resolve_to_rgb_bytes())
    # Save a representative frame
    fb0, _ = _render_scene("torus", w, h, msaa=msaa, rotation_y=0.4, textures=textures)
    save_png(os.path.join(out, "torus.png"), fb0.width, fb0.height, fb0.resolve_to_rgb_bytes())
    print(f"  → {out}/torus_anim.html  {out}/torus.png")

    # D2: Showcase scene
    print("\n[D2] Showcase scene (sphere+torus+cylinder+box)…", flush=True)
    fb, el = _render_scene("showcase", w, h, msaa=msaa, textures=textures)
    save_png(os.path.join(out, "showcase.png"), fb.width, fb.height,
             fb.resolve_to_rgb_bytes())
    print(f"  → {out}/showcase.png  ({el:.2f}s)")

    # D3: Shadow demo comparison
    print("\n[D3] Shadow mapping comparison…", flush=True)
    renders = []
    for shadow in [False, True]:
        fb, el = _render_scene("shadow_demo", w, h, msaa=msaa,
                               shadow=shadow, textures=textures)
        renders.append({
            'label': "With PCF Shadow Mapping" if shadow else "No Shadows",
            'png_bytes': _fb_to_png(fb),
            'caption': f"{'3×3 PCF kernel · ' if shadow else ''}{el:.2f}s",
        })
        nm = 'shadow_on' if shadow else 'shadow_off'
        save_png(os.path.join(out, f"{nm}.png"), fb.width, fb.height, fb.resolve_to_rgb_bytes())
        print(f"  shadow={'on' if shadow else 'off'}: {el:.2f}s", flush=True)
    html = build_comparison_html(renders, "Prism — Shadow Mapping")
    with open(os.path.join(out, "shadow_compare.html"), 'w') as f: f.write(html)
    print(f"  → {out}/shadow_compare.html")

    # D4: Showcase animation
    print(f"\n[D4] Showcase animation ({n} frames)…", flush=True)
    frames = []
    for i in range(n):
        angle = 2*math.pi*i/n
        fb, el = _render_scene("showcase", w, h, msaa=msaa, rotation_y=angle,
                               textures=textures)
        frames.append(_fb_to_png(fb))
        print(f"  frame {i+1}/{n} ({el:.2f}s)", flush=True)
    html = build_html_viewer(frames, title="Prism — Showcase",
                             fps=args.fps, width=w, height=h,
                             caption="Torus · Earth sphere · Marble cylinder · Box · Ground plane")
    with open(os.path.join(out, "showcase_anim.html"), 'w') as f: f.write(html)
    print(f"  → {out}/showcase_anim.html")

    # D5: Cornell box
    print("\n[D5] Cornell box…", flush=True)
    fb, el = _render_scene("cornell", w, h, msaa=msaa, textures=textures)
    save_png(os.path.join(out, "cornell.png"), fb.width, fb.height,
             fb.resolve_to_rgb_bytes())
    print(f"  → {out}/cornell.png  ({el:.2f}s)")

    print(f"\nDemo complete. Output in: {out}/")


# ── Parser ──

def build_parser():
    p = argparse.ArgumentParser(
        prog='prism',
        description='Prism — from-scratch software 3D rasterizer')
    p.add_argument('--width',  type=int, default=320)
    p.add_argument('--height', type=int, default=320)
    p.add_argument('--msaa',   type=int, default=1, choices=[1,2],
                   help='MSAA multiplier (1=off, 2=4 samples)')
    sub = p.add_subparsers(dest='cmd')

    # render
    r = sub.add_parser('render', help='Render a named scene to PNG')
    r.add_argument('scene', nargs='?', default='torus',
                   choices=['torus','sphere','cornell','shadow_demo','showcase'])
    r.add_argument('--shadow', action='store_true')

    # animate
    an = sub.add_parser('animate', help='Render rotation animation to HTML')
    an.add_argument('scene', nargs='?', default='torus',
                    choices=['torus','sphere','cornell','shadow_demo','showcase'])
    an.add_argument('--frames', type=int, default=24)
    an.add_argument('--fps',    type=int, default=20)
    an.add_argument('--shadow', action='store_true')

    # obj
    ob = sub.add_parser('obj', help='Load and render a Wavefront OBJ file')
    ob.add_argument('--file', required=True)
    ob.add_argument('--rotate', type=float, default=0.0,
                    help='Y-axis rotation in degrees')
    ob.add_argument('--wireframe', action='store_true')
    ob.add_argument('--animate', action='store_true')
    ob.add_argument('--frames', type=int, default=24)

    # shadows
    sh = sub.add_parser('shadows', help='Shadow mapping comparison')

    # compare
    cp = sub.add_parser('compare', help='Render wireframe/phong/texture comparison')
    cp.add_argument('scene', nargs='?', default='torus',
                    choices=['torus','sphere','cornell','shadow_demo','showcase'])

    # info
    sub.add_parser('info', help='Print pipeline info')

    # demo
    dm = sub.add_parser('demo', help='Run full demo')
    dm.add_argument('--frames', type=int, default=24)
    dm.add_argument('--fps',    type=int, default=20)

    return p


def main():
    p = build_parser()
    args = p.parse_args()

    # Apply rotate degrees → radians for obj subcommand
    if args.cmd == 'obj' and hasattr(args, 'rotate'):
        args.rotate = math.radians(args.rotate)

    dispatch = {
        'render':  cmd_render,
        'animate': cmd_animate,
        'obj':     cmd_obj,
        'shadows': cmd_shadows,
        'compare': cmd_compare,
        'info':    cmd_info,
        'demo':    cmd_demo,
    }
    if args.cmd is None:
        p.print_help()
        sys.exit(0)
    fn = dispatch.get(args.cmd)
    if fn is None:
        p.print_help(); sys.exit(1)
    fn(args)


if __name__ == '__main__':
    main()
