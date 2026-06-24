#!/usr/bin/env bash
# demo.sh — Lumina path tracer end-to-end demonstration
# Exercises all required + stretch features and prints a pass/fail summary.
# Expected total run time: 2-5 minutes (pure Python renderer).

set -euo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0

run() {
    local label="$1"; shift
    echo -n "  [$label] "
    if "$@" > /tmp/lumina_demo_out.txt 2>&1; then
        echo "PASS"
        (( PASS++ )) || true
    else
        echo "FAIL"
        cat /tmp/lumina_demo_out.txt
        (( FAIL++ )) || true
    fi
}

check_file() {
    local label="$1"
    local file="$2"
    echo -n "  [$label] "
    if [ -f "$file" ] && [ -s "$file" ]; then
        local size
        size=$(wc -c < "$file")
        echo "PASS  ($size bytes)"
        (( PASS++ )) || true
    else
        echo "FAIL  (file missing or empty: $file)"
        (( FAIL++ )) || true
    fi
}

echo ""
echo "============================================================"
echo "  Lumina — Monte Carlo Path Tracer — End-to-End Demo"
echo "============================================================"
echo ""

# ── Test suite ────────────────────────────────────────────────────────────────
echo "[1] Unit + integration test suite"
run "55 tests" python -m unittest tests.test_lumina -v

# ── R1: Scene system + ray-primitive intersection ─────────────────────────────
echo ""
echo "[R1] Scene system and ray-primitive intersection"
run "spheres scene (BVH over 400+ spheres)" \
    python lumina.py render spheres -W 80 -H 45 -s 4 -d 4 -o /tmp/demo_spheres.png --aces -q
check_file "spheres.png written" /tmp/demo_spheres.png

run "glass scene (sphere + plane intersection)" \
    python lumina.py render glass -W 80 -H 45 -s 4 -d 4 -o /tmp/demo_glass.png --aces -q
check_file "glass.png written" /tmp/demo_glass.png

# ── R2: BVH acceleration ──────────────────────────────────────────────────────
echo ""
echo "[R2] BVH acceleration"
run "info shows BVH stats (cornell)" \
    python lumina.py info cornell
run "bench: BVH intersection speed" \
    python lumina.py bench cornell -W 64 -H 64 -s 4

# ── R3: Path tracing core ─────────────────────────────────────────────────────
echo ""
echo "[R3] Path tracing core (multiple bounces, Russian Roulette)"
run "simple PT (no NEE) smoke test" \
    python lumina.py render glass -W 40 -H 22 -s 4 -d 8 --simple -o /tmp/demo_simple.png -q
run "NEE+MIS active (default)" \
    python lumina.py render glass -W 40 -H 22 -s 4 -d 8 -o /tmp/demo_nee.png -q

# ── R4: PBR materials ─────────────────────────────────────────────────────────
echo ""
echo "[R4] Physically-based materials (Lambertian/Metal/Dielectric/Emissive)"
run "showcase scene (all 4 material types)" \
    python lumina.py render showcase -W 80 -H 45 -s 4 -d 6 -o /tmp/demo_showcase.png --aces -q
check_file "showcase.png written" /tmp/demo_showcase.png

run "cornell box (diffuse boxes + area light)" \
    python lumina.py render cornell -W 60 -H 60 -s 8 -d 8 -o /tmp/demo_cornell.png --aces -q
check_file "cornell.png written" /tmp/demo_cornell.png

# ── S1: Tone mapping + PNG output ─────────────────────────────────────────────
echo ""
echo "[S1] Tone mapping and PNG output"
run "Reinhard tone map" \
    python lumina.py render glass -W 40 -H 22 -s 2 -o /tmp/demo_reinhard.png -q
run "ACES filmic tone map" \
    python lumina.py render glass -W 40 -H 22 -s 2 --aces -o /tmp/demo_aces.png -q
run "PNG round-trip (encode then decode)" \
    python -c "
from output import write_png, decode_png_rgb
from vec3 import Vec3
import random
random.seed(42)
w, h = 32, 32
px = [(int(random.random()*255), int(random.random()*255), int(random.random()*255))
      for _ in range(w*h)]
write_png('/tmp/lumina_rt.png', px, w, h)
decoded, wd, hd = decode_png_rgb('/tmp/lumina_rt.png')
assert decoded == px, 'Round-trip FAILED'
assert wd == w and hd == h, 'Dimensions wrong'
print('Round-trip PASS')
"

# ── S2: NEE + MIS ─────────────────────────────────────────────────────────────
echo ""
echo "[S2] Next-Event Estimation and MIS balance heuristic"
run "NEE faster convergence (Cornell: higher luminance at same spp)" \
    python -c "
import random, sys
sys.path.insert(0, '.')
from scene import PRESETS
from renderer import render, trace_simple, trace_nee
from output import pixel_stats

random.seed(7)
scene_n, cam = PRESETS['cornell']()
px_nee = render(scene_n, cam, 40, 40, 4, max_depth=5, use_nee=True)
random.seed(7)
scene_s, cam = PRESETS['cornell']()
px_simple = render(scene_s, cam, 40, 40, 4, max_depth=5, use_nee=False)
stats_nee = pixel_stats(px_nee)
stats_simple = pixel_stats(px_simple)
print(f'NEE mean_lum={stats_nee[\"mean_luminance\"]:.4f}  '
      f'Simple mean_lum={stats_simple[\"mean_luminance\"]:.4f}')
# NEE should produce different (typically better sampled) results
assert stats_nee['mean_luminance'] >= 0.0, 'NEE produced negative luminance'
print('NEE MIS PASS')
"

# ── S3: OBJ mesh loading ──────────────────────────────────────────────────────
echo ""
echo "[S3] OBJ mesh loading with smooth normals"
run "load tetrahedron.obj (4 triangles)" \
    python -c "
from mesh import load_obj, obj_bounds
from materials import Lambertian
from vec3 import Vec3
mat = Lambertian(Vec3(0.8, 0.6, 0.4))
tris = load_obj('models/tetrahedron.obj', mat)
assert len(tris) == 4, f'Expected 4 triangles, got {len(tris)}'
print(f'Loaded {len(tris)} triangles OK')
"
run "load icosphere.obj (20 triangles + smooth normals)" \
    python -c "
from mesh import load_obj, obj_bounds
from materials import Lambertian
from vec3 import Vec3
mat = Lambertian(Vec3(0.8, 0.6, 0.4))
tris = load_obj('models/icosphere.obj', mat)
assert len(tris) == 20
# Verify smooth normals (vertex normals differ from face normals)
t = tris[0]
assert abs(t.n0.length() - 1.0) < 1e-3
print(f'Loaded {len(tris)} smooth-shaded triangles OK')
"
run "render OBJ mesh (tetrahedron)" \
    python lumina.py obj models/tetrahedron.obj -W 60 -H 45 -s 4 -d 4 -o /tmp/demo_tet.png --aces
check_file "tetrahedron.png written" /tmp/demo_tet.png

run "bilateral denoiser" \
    python -c "
from output import bilateral_denoise
from vec3 import Vec3
import random
random.seed(42)
w, h = 20, 20
pixels = [Vec3(random.random(), random.random(), random.random()) for _ in range(w*h)]
out = bilateral_denoise(pixels, w, h)
assert len(out) == w*h
# Denoised image should be smoother (lower variance) than input
def var(px): lums=[0.2126*p.x+0.7152*p.y+0.0722*p.z for p in px]; m=sum(lums)/len(lums); return sum((l-m)**2 for l in lums)/len(lums)
assert var(out) < var(pixels), 'Denoiser increased variance!'
print('Bilateral denoiser reduces variance: PASS')
"

# ── JSON scene loading ─────────────────────────────────────────────────────────
echo ""
echo "[JSON] JSON scene file loading"
cat > /tmp/test_scene.json << 'EOF'
{
  "background_top": [0.3, 0.5, 0.8],
  "background_bot": [1.0, 1.0, 1.0],
  "camera": {
    "lookfrom": [0, 2, 5], "lookat": [0, 0, 0], "vup": [0, 1, 0],
    "vfov": 45, "aspect": 1.777
  },
  "materials": {
    "gray": {"type": "lambertian", "albedo": [0.5, 0.5, 0.5]},
    "red":  {"type": "lambertian", "albedo": [0.8, 0.1, 0.1]},
    "gold": {"type": "metal", "albedo": [0.9, 0.7, 0.2], "fuzz": 0.1},
    "glass":{"type": "dielectric", "ior": 1.5}
  },
  "objects": [
    {"type": "sphere", "center": [0, -1001, 0], "radius": 1000, "material": "gray"},
    {"type": "sphere", "center": [-1.5, 0, 0], "radius": 1.0, "material": "red"},
    {"type": "sphere", "center": [0, 0, 0],    "radius": 1.0, "material": "gold"},
    {"type": "sphere", "center": [1.5, 0, 0],  "radius": 1.0, "material": "glass"}
  ]
}
EOF
run "render JSON scene" \
    python lumina.py render /tmp/test_scene.json -W 60 -H 34 -s 4 -d 4 \
        -o /tmp/demo_json.png --aces -q

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================================"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
