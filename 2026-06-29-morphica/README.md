# Morphica

**Generative Algorithmic Art Engine** — four families of mathematical art, each
rendered from scratch in Python to SVG and PNG, with a self-contained interactive
browser viewer.

---

## What it is

Morphica is a unified CLI for producing algorithmically-generated artwork from
four distinct branches of mathematics:

| Family | Algorithm | Output |
|--------|-----------|--------|
| **L-Systems** | Rewriting rules + turtle-graphics rasteriser | SVG or PNG |
| **Reaction-Diffusion** | Gray-Scott PDE solver (Gray-Scott 1984) | PNG |
| **Strange Attractors** | ODE/map integrators + histogram density | PNG |
| **Voronoi + Stippling** | Nearest-site sweep + Lloyd relaxation | SVG or PNG |

Everything is from-scratch Python:
- Hand-rolled PNG encoder (IHDR/IDAT/IEND, Sub filter, zlib, CRC-32)
- Custom SVG serialiser
- No rendering libraries (no Pillow, no Cairo, no matplotlib)
- Numpy used only as an optional accelerator for the RD solver (falls back to
  pure Python automatically)

---

## How to run

```bash
# list all presets, attractors, and palettes
python3 morphica.py list

# L-system
python3 morphica.py lsystem hilbert --format png --color '#00CFFF'
python3 morphica.py lsystem barnsley --format svg

# Reaction-diffusion
python3 morphica.py rd worms --size 200 --steps 5000 --palette viridis
python3 morphica.py rd spots --size 200 --steps 5000 --palette plasma

# Strange attractor
python3 morphica.py attractor lorenz --width 800 --height 800
python3 morphica.py attractor clifford --palette neon

# Voronoi diagram
python3 morphica.py voronoi --points 80 --lloyd 5 --format svg
python3 morphica.py stipple --points 300 --seed 7

# Animation: export frame sequences
python3 morphica.py animate lsystem dragon --frames 8 --seed 0
python3 morphica.py animate attractor clifford --frames 12
python3 morphica.py animate rd worms --frames 6

# Interactive browser viewer (self-contained HTML)
python3 morphica.py viewer -o viewer.html
# → open viewer.html in any browser

# Full feature demo
bash demo.sh
```

### Tests
```bash
python3 tests/test_morphica.py
# → 58 tests, all green
```

---

## Feature list

### Required (all shipped)
1. **L-System Engine** — 9 built-in presets (Sierpinski, Koch, Dragon, Barnsley,
   Plant, Hilbert, Pentigree, Bush, Stochastic Plant); stochastic rules with
   weighted probabilistic production; seeded for reproducibility; turtle
   interpreter producing SVG paths or Bresenham-rasterised PNG; auto-scaling
   layout with configurable stroke colour and background.

2. **Gray-Scott Reaction-Diffusion** — 6 named parameter presets (coral, mitosis,
   worms, maze, spots, fingerprint); numpy-accelerated explicit Euler solver with
   pure-Python fallback; 5-point discrete Laplacian with wrap-around boundaries;
   configurable grid size and step count; output mapped through any named palette.

3. **Strange Attractors** (6 kinds) — Lorenz butterfly (3-D, σ=10, ρ=28, β=8/3),
   Rössler, Clifford map, De Jong map, Pickover (3-D → 2-D), Duffing map; all
   use log-scaled histogram density colouring (flame-algorithm style) rather than
   scatter-plot; arbitrary resolution; seeded orbit initialisation.

4. **Voronoi Diagram + Weighted Stippling** — brute-force nearest-site
   rasterisation; Lloyd relaxation (centroidal Voronoi tessellation) for uniform
   spacing; rejection-sampled weighted stippling (point density follows a
   luminance field); SVG and PNG output modes; guard against degenerate inputs.

### Stretch (all 3 shipped)
5. **Interactive Browser Viewer** — single-file self-contained HTML + JS; L-system
   growth animation (play/pause/scrub/step); attractor orbit rendered from embedded
   gallery; keyboard navigation; PNG frame export from canvas; no server required.

6. **Palette System** — 12 named palettes (viridis, plasma, magma, fire, ice,
   ocean, forest, neon, grayscale, coolwarm, twilight, sunset); `apply_palette`
   with custom vmin/vmax/gamma; HSV-cycle palette for Voronoi cell colouring;
   palette blending used in `animate_palette_cycle`.

7. **Animation / Frame Export** — `morphica animate lsystem` exports one PNG per
   growth step; `morphica animate attractor` exports orbit-buildup frames with
   consistent global bounding box; `morphica animate rd` exports Gray-Scott
   time-evolution snapshots; palette-cycling animation over any field (RD, etc.);
   GIF assembly via ImageMagick `convert` (documented in output).

---

## Why I chose this today

The LEDGER was heavy on algorithms with a single mode of output — SAT solvers,
physics engines, language VMs. What was missing was a project where *the output
itself is the point*: something you'd hang on a wall. Morphica lets four
completely different branches of mathematics each produce their own aesthetic
signature, and the contrast between them (the organic worm-like RD patterns vs
the angular self-similarity of L-systems vs the ethereal density clouds of
attractors) makes the package more than the sum of its parts.

The flame-algorithm attractor rendering was the most technically satisfying: using
a log-scaled histogram accumulator rather than a simple scatter plot transforms
chaotic orbits into photographic-quality images where you can see both the dense
core structure and the sparse outer tendrils simultaneously.

---

## Where a human could take this next

- **GPU acceleration** — the RD solver, Voronoi rasteriser, and attractor histogram
  are all trivially parallelisable; a CUDA/Metal/WGSL compute shader would give
  100–1000× speedup and allow real-time interactive exploration.
- **Animated GIF/MP4 output** — wire the frame sequences directly to ffmpeg or
  Pillow to produce videos without the ImageMagick dependency.
- **Parameter discovery** — add a mode that random-walks the Gray-Scott (F, k)
  parameter space and auto-saves the most visually interesting results, using a
  simple image variance metric to skip uniform/noisy frames.
- **Custom rule editor** — a web UI where you type L-system axioms and rules and
  see the turtle trace update live (the JavaScript engine already exists in the
  viewer; it just needs an input panel).
- **Attractor parameter sliders** — the clifford and dejong maps take 4 parameters
  (a, b, c, d); a four-slider interactive explorer would reveal a vast landscape of
  shapes in real time.
- **Fortune's algorithm** — the dead `fortune_voronoi` function is partially
  written; completing it would enable true polygon-based SVG Voronoi output
  (proper `<polygon>` elements, not rasterised rectangles) for infinitely scalable
  vector graphics.
- **Hybrid compositions** — use a Voronoi diagram to partition the canvas and fill
  each cell with a different L-system or attractor, treating the Voronoi as a
  layout engine for generative subcompositions.
