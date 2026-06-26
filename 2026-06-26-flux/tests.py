"""
Flux test suite — physics correctness, scene behaviour, CLI, PNG round-trip.

Run with:  python3 tests.py
Exit 0 = all pass; non-zero = failure count.
"""

import sys
import os
import json
import math
import subprocess
import tempfile
import shutil
import numpy as np

# Ensure we can import from the project directory
sys.path.insert(0, os.path.dirname(__file__))

from fluid import FluidGrid
from render import encode_png, decode_png, render_frame, RENDER_MODES
from scenes import SCENES, load_json_scene

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _failures
    if condition:
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}" + (f"  [{detail}]" if detail else ""))
        _failures += 1


def section(title: str) -> None:
    print(f"\n── {title} ──")


# ---------------------------------------------------------------------------
# 1. Solver fundamentals
# ---------------------------------------------------------------------------

section("Solver — divergence-free")

def make_grid(N=32, dt=0.15, **kw):
    return FluidGrid(N=N, dt=dt, **kw)

fluid = make_grid()
fluid.u[1:-1, 1:-1] = np.random.randn(32, 32) * 2.0
fluid.v[1:-1, 1:-1] = np.random.randn(32, 32) * 2.0
fluid.step()
div = fluid.divergence_rms()
check("random IC → div_rms < 0.05 after step", div < 0.05, f"div_rms={div:.5f}")

# Run 50 steps and check divergence stays low
for _ in range(49):
    fluid.step()
div50 = fluid.divergence_rms()
check("50 steps random IC → div_rms < 0.01", div50 < 0.01, f"div_rms={div50:.5f}")

section("Solver — NaN / overflow safety")

fluid2 = make_grid(vort_scale=10.0, dt=1.0)
fluid2.u[1:-1, 1:-1] = 5.0
fluid2.v[1:-1, 1:-1] = -5.0
for _ in range(20):
    fluid2.step()
has_nan = np.isnan(fluid2.u).any() or np.isnan(fluid2.v).any()
check("dt=1.0 + vort_scale=10 → no NaN after 20 steps", not has_nan)

section("Solver — gravity")

fluid3 = make_grid(gravity=0.5)
ch = fluid3.add_dye((1.0, 1.0, 1.0))
fluid3.inject_dye(0, 0.5, 0.05, 0.1, amount=2.0)
fluid3.inject_velocity(0.5, 0.05, 0.1, 0.0, 0.0)
for _ in range(30):
    fluid3.step()
J, I = np.meshgrid(range(32), range(32), indexing='ij')
dye = fluid3.dyes[0].density[1:-1, 1:-1]
mass = dye.sum()
cy_mean = (J * dye).sum() / (mass * 32) if mass > 0 else 0.5
check("gravity=+0.5 moves dye downward (cy_mean > 0.2)", cy_mean > 0.2, f"cy_mean={cy_mean:.3f}")

# Negative gravity (buoyancy)
fluid4 = make_grid(gravity=-0.5)
ch = fluid4.add_dye((1.0, 1.0, 1.0))
fluid4.inject_dye(0, 0.5, 0.95, 0.1, amount=2.0)
fluid4.inject_velocity(0.5, 0.95, 0.1, 0.0, -0.5)
for _ in range(30):
    fluid4.step()
dye4 = fluid4.dyes[0].density[1:-1, 1:-1]
mass4 = dye4.sum()
cy_mean4 = (J * dye4).sum() / (mass4 * 32) if mass4 > 0 else 0.5
check("gravity=-0.5 moves dye upward (cy_mean < 0.8)", cy_mean4 < 0.8, f"cy_mean={cy_mean4:.3f}")

section("Solver — obstacles")

fluid5 = make_grid()
fluid5.add_obstacle_rect(0.3, 0.3, 0.7, 0.7)
fluid5.u[1:-1, 1:-1] = 2.0
fluid5.v[1:-1, 1:-1] = -2.0
for _ in range(10):
    fluid5.step()
obs_cells = fluid5.obstacles[1:-1, 1:-1]
u_in_obs = float(np.abs(fluid5.u[1:-1, 1:-1][obs_cells]).max())
v_in_obs = float(np.abs(fluid5.v[1:-1, 1:-1][obs_cells]).max())
check("velocity inside obstacle cells = 0", u_in_obs == 0.0 and v_in_obs == 0.0,
      f"u_max={u_in_obs:.6f}, v_max={v_in_obs:.6f}")

# Obstacles with vort_scale=0 (the bug from Phase 3)
fluid6 = make_grid(vort_scale=0.0)
fluid6.add_obstacle_circle(0.5, 0.5, 0.15)
fluid6.u[1:-1, 1:-1] = 3.0
for _ in range(5):
    fluid6.step()
obs6 = fluid6.obstacles[1:-1, 1:-1]
u_obs6 = float(np.abs(fluid6.u[1:-1, 1:-1][obs6]).max())
check("vort_scale=0: velocity in obstacle = 0 after step", u_obs6 == 0.0,
      f"u_max={u_obs6:.6f}")

section("Solver — inject guard")

fluid7 = make_grid()
fluid7.add_dye((1.0, 1.0, 1.0))
try:
    fluid7.inject_dye(99, 0.5, 0.5, 0.1)  # invalid channel — should not raise
    check("inject_dye invalid channel → no exception", True)
except Exception as e:
    check("inject_dye invalid channel → no exception", False, str(e))

section("Solver — vorticity confinement enhancement")

fluid8 = make_grid(vort_scale=5.0)
fluid8.add_dye((1.0, 1.0, 1.0))
fluid8.inject_velocity(0.5, 0.5, 0.2, 2.0, 0.5)
vort_before = float(np.abs(fluid8.vorticity()[1:-1, 1:-1]).max())
for _ in range(10):
    fluid8.step()
vort_after = float(np.abs(fluid8.vorticity()[1:-1, 1:-1]).max())
fluid8b = make_grid(vort_scale=0.0)
fluid8b.add_dye((1.0, 1.0, 1.0))
fluid8b.inject_velocity(0.5, 0.5, 0.2, 2.0, 0.5)
for _ in range(10):
    fluid8b.step()
vort_no_confinement = float(np.abs(fluid8b.vorticity()[1:-1, 1:-1]).max())
check("vorticity confinement enhances |curl|",
      vort_after > vort_no_confinement * 1.1,
      f"with={vort_after:.4f}  without={vort_no_confinement:.4f}")

# ---------------------------------------------------------------------------
# 2. Scene behaviour
# ---------------------------------------------------------------------------

section("Scenes — all 5 stable for full frame count")

def run_scene(name):
    fluid, inject, meta = SCENES[name](64)
    for _ in range(meta["frames"]):
        inject(fluid.frame)
        fluid.step()
    speed = float(np.sqrt(fluid.u[1:-1,1:-1]**2 + fluid.v[1:-1,1:-1]**2).max())
    div   = fluid.divergence_rms()
    has_nan = bool(np.isnan(fluid.u).any() or np.isnan(fluid.v).any())
    return fluid, speed, div, has_nan

for sname in SCENES:
    fluid, speed, div, has_nan = run_scene(sname)
    check(f"{sname}: no NaN, div_rms<0.01, speed<20",
          not has_nan and div < 0.01 and speed < 20.0,
          f"speed={speed:.2f} div={div:.5f} nan={has_nan}")

section("Scenes — smoke rises")

fluid_s, inject_s, _ = SCENES["smoke"](64)
J64, I64 = np.meshgrid(range(64), range(64), indexing='ij')
for _ in range(80):
    inject_s(fluid_s.frame)
    fluid_s.step()
total = sum(d.density[1:-1,1:-1] for d in fluid_s.dyes)
mass = total.sum()
cy_s = (J64 * total).sum() / (mass * 64) if mass > 0 else 0.5
check(f"smoke: dye center cy={cy_s:.3f} < 0.90 (above source)", cy_s < 0.90,
      f"cy={cy_s:.3f}")

section("Scenes — ink falls")

fluid_i, inject_i, _ = SCENES["ink"](64)
for _ in range(80):
    inject_i(fluid_i.frame)
    fluid_i.step()
total_i = sum(d.density[1:-1,1:-1] for d in fluid_i.dyes)
mass_i = total_i.sum()
cy_i = (J64 * total_i).sum() / (mass_i * 64) if mass_i > 0 else 0.5
check(f"ink: dye center cy={cy_i:.3f} > 0.10 (below source)", cy_i > 0.10,
      f"cy={cy_i:.3f}")

section("Scenes — fire rises")

fluid_f, inject_f, _ = SCENES["fire"](64)
for _ in range(80):
    inject_f(fluid_f.frame)
    fluid_f.step()
total_f = sum(d.density[1:-1,1:-1] for d in fluid_f.dyes)
mass_f = total_f.sum()
cy_f = (J64 * total_f).sum() / (mass_f * 64) if mass_f > 0 else 0.5
check(f"fire: dye center cy={cy_f:.3f} < 0.90 (above source)", cy_f < 0.90,
      f"cy={cy_f:.3f}")

section("Scenes — wind creates rightward flow")

fluid_w, inject_w, _ = SCENES["wind"](64)
for _ in range(50):
    inject_w(fluid_w.frame)
    fluid_w.step()
u_mean = float(fluid_w.u[1:-1,1:-1].mean())
check(f"wind: mean u (rightward) > 0.2: u_mean={u_mean:.3f}", u_mean > 0.2,
      f"u_mean={u_mean:.3f}")

section("Scenes — vortex has non-zero vorticity")

fluid_v, inject_v, _ = SCENES["vortex"](64)
for _ in range(50):
    inject_v(fluid_v.frame)
    fluid_v.step()
curl_max = float(np.abs(fluid_v.vorticity()[1:-1,1:-1]).max())
check(f"vortex: |curl|_max={curl_max:.4f} > 0.001", curl_max > 0.001,
      f"curl={curl_max:.4f}")

# ---------------------------------------------------------------------------
# 3. Render
# ---------------------------------------------------------------------------

section("Render — all modes, correct output shape")

fluid_r, inject_r, _ = SCENES["smoke"](32)
for _ in range(5):
    inject_r(fluid_r.frame)
    fluid_r.step()

for mode in RENDER_MODES:
    rgb = render_frame(fluid_r, mode=mode, scale=2)
    ok_shape = (rgb.shape == (64, 64, 3))
    ok_dtype = (rgb.dtype == np.uint8)
    check(f"render mode '{mode}': shape (64,64,3) uint8",
          ok_shape and ok_dtype,
          f"got {rgb.shape} {rgb.dtype}")

section("Render — PNG round-trip")

rgb_orig = render_frame(fluid_r, mode="composite", scale=4)
png_bytes = encode_png(rgb_orig)
check("encode_png returns bytes starting with PNG signature",
      png_bytes[:8] == b"\x89PNG\r\n\x1a\n")

rgb_dec = decode_png(png_bytes)
check("decode_png → same shape as original",
      rgb_dec.shape == rgb_orig.shape,
      f"{rgb_dec.shape} vs {rgb_orig.shape}")
check("decode_png → pixel values match (max diff = 0)",
      int(np.abs(rgb_dec.astype(int) - rgb_orig.astype(int)).max()) == 0)

section("Render — scale factor")

rgb1 = render_frame(fluid_r, mode="dye", scale=1)
rgb4 = render_frame(fluid_r, mode="dye", scale=4)
check("scale=1 → 32×32; scale=4 → 128×128",
      rgb1.shape == (32, 32, 3) and rgb4.shape == (128, 128, 3),
      f"{rgb1.shape}, {rgb4.shape}")

# ---------------------------------------------------------------------------
# 4. JSON scene loading
# ---------------------------------------------------------------------------

section("JSON scene loading")

json_path = os.path.join(os.path.dirname(__file__), "example_scene.json")
if os.path.isfile(json_path):
    fluid_j, inject_j, meta_j = load_json_scene(json_path)
    check("load_json_scene: correct name",
          meta_j["name"] == "channel_flow", f"got {meta_j['name']}")
    check("load_json_scene: obstacles created",
          fluid_j.obstacles.sum() > 0, f"obs={fluid_j.obstacles.sum()}")
    check("load_json_scene: 2 dye channels",
          len(fluid_j.dyes) == 2, f"got {len(fluid_j.dyes)}")
    for _ in range(30):
        inject_j(fluid_j.frame)
        fluid_j.step()
    speed_j = float(np.sqrt(fluid_j.u[1:-1,1:-1]**2+fluid_j.v[1:-1,1:-1]**2).max())
    check("json scene: stable after 30 steps", speed_j < 10.0, f"speed={speed_j:.3f}")
else:
    print(f"  [SKIP] example_scene.json not found at {json_path}")

section("JSON scene — inline dict")

tmp_path = tempfile.mktemp(suffix=".json")
scene_dict = {
    "name": "test_gravity",
    "N": 32, "dt": 0.15, "visc": 0.0, "diff": 0.0,
    "vort_scale": 0.0, "gravity": 0.3,
    "dyes": [{"color": [1.0, 0.0, 0.0]}],
    "obstacles": [],
    "injections": [
        {"frames": [0, 100], "dye": 0,
         "cx": 0.5, "cy": 0.1, "radius": 0.1, "amount": 2.0,
         "vx": 0.0, "vy": 0.0}
    ],
    "frames": 50,
    "description": "Inline test"
}
with open(tmp_path, "w") as f:
    json.dump(scene_dict, f)
fluid_t, inject_t, meta_t = load_json_scene(tmp_path)
check("inline json: correct frame count", meta_t["frames"] == 50)
for _ in range(50):
    inject_t(fluid_t.frame)
    fluid_t.step()
dye_t = fluid_t.dyes[0].density[1:-1, 1:-1]
J32, _ = np.meshgrid(range(32), range(32), indexing='ij')
mass_t = dye_t.sum()
cy_t = (J32 * dye_t).sum() / (mass_t * 32) if mass_t > 0 else 0.5
check("inline json gravity=+0.3: dye moves down (cy > 0.2)", cy_t > 0.2,
      f"cy={cy_t:.3f}")
os.unlink(tmp_path)

# ---------------------------------------------------------------------------
# 5. CLI smoke-test
# ---------------------------------------------------------------------------

section("CLI — info command")

cli_path = os.path.join(os.path.dirname(__file__), "cli.py")
result = subprocess.run(
    [sys.executable, cli_path, "info", "--scene", "smoke", "--N", "32"],
    capture_output=True, text=True
)
check("cli info: exit 0", result.returncode == 0, result.stderr.strip())
check("cli info: prints grid size", "32×32" in result.stdout,
      repr(result.stdout[:200]))

section("CLI — render command")

tmpdir = tempfile.mkdtemp()
try:
    result2 = subprocess.run(
        [sys.executable, cli_path, "render",
         "--scene", "smoke", "--N", "32", "--frames", "5",
         "--mode", "composite", "--scale", "2", "--output", tmpdir],
        capture_output=True, text=True
    )
    check("cli render: exit 0", result2.returncode == 0, result2.stderr.strip())
    frames = sorted(f for f in os.listdir(tmpdir) if f.endswith(".png"))
    check("cli render: wrote 5 PNG frames", len(frames) == 5, f"got {len(frames)}")
    if frames:
        with open(os.path.join(tmpdir, frames[0]), "rb") as fp:
            sig = fp.read(8)
        check("cli render: frame_0000.png is a valid PNG",
              sig == b"\x89PNG\r\n\x1a\n", repr(sig))
        rgb_c = decode_png(open(os.path.join(tmpdir, frames[0]), "rb").read())
        check("cli render: frame has correct dimensions (64×64)",
              rgb_c.shape == (64, 64, 3), f"{rgb_c.shape}")
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

section("CLI — anim command")

tmpdir2 = tempfile.mkdtemp()
try:
    out_html = os.path.join(tmpdir2, "test_anim.html")
    result3 = subprocess.run(
        [sys.executable, cli_path, "anim",
         "--scene", "vortex", "--N", "32", "--frames", "8",
         "--mode", "dye", "--output", out_html],
        capture_output=True, text=True
    )
    check("cli anim: exit 0", result3.returncode == 0, result3.stderr.strip())
    check("cli anim: HTML file written", os.path.isfile(out_html))
    if os.path.isfile(out_html):
        html_text = open(out_html).read()
        check("cli anim: HTML has FRAMES array", "const FRAMES" in html_text)
        check("cli anim: HTML has base64 PNG data",
              "data:image/png;base64," in html_text)
finally:
    shutil.rmtree(tmpdir2, ignore_errors=True)

section("CLI — all render modes accepted")

for mode in RENDER_MODES:
    result_m = subprocess.run(
        [sys.executable, cli_path, "info", "--scene", "smoke", "--N", "16"],
        capture_output=True, text=True
    )
    check(f"mode '{mode}' listed in render modes",
          mode in result_m.stdout, result_m.stdout[-100:])

section("CLI — unknown scene exits non-zero")

result4 = subprocess.run(
    [sys.executable, cli_path, "render", "--scene", "nonexistent_scene_xyz"],
    capture_output=True, text=True
)
check("cli unknown scene: non-zero exit", result4.returncode != 0)

section("CLI — JSON scene via render")

json_path2 = os.path.join(os.path.dirname(__file__), "example_scene.json")
if os.path.isfile(json_path2):
    tmpdir3 = tempfile.mkdtemp()
    try:
        result5 = subprocess.run(
            [sys.executable, cli_path, "render",
             "--scene", json_path2, "--N", "32", "--frames", "5",
             "--output", tmpdir3],
            capture_output=True, text=True
        )
        check("cli render json scene: exit 0", result5.returncode == 0,
              result5.stderr.strip())
    finally:
        shutil.rmtree(tmpdir3, ignore_errors=True)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
if _failures == 0:
    print(f"  {PASS}  All tests passed")
else:
    print(f"  {FAIL}  {_failures} test(s) FAILED")
print(f"{'='*50}")

sys.exit(_failures)
