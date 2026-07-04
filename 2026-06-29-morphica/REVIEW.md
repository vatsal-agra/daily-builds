# Morphica — Code Review

Reviewer: hostile automated review  
Date: 2026-06-29  
Scope: all eight source files + runtime testing of every command and edge case

---

## CRITICAL

### C-1 · Duffing attractor always crashes with OverflowError  
**File:** `attractors.py` lines 47–50, 201–210  
**Confirmed:** `python3 morphica.py attractor duffing` raises `OverflowError: (34, 'Numerical result out of range')` during warmup at step ~32.

The Duffing map `ny = -b*y + a*x - x**3` with `a=2.75` is not bounded — it diverges to infinity for the default initial conditions. The parameters `(a=2.75, b=0.2)` do not produce a dissipative strange attractor; they send the orbit to infinity. No guard (`math.isfinite`, try/except, orbit-escape check) exists anywhere in `_orbit_duffing` or `render_attractor`. The attractor is listed in `ATTRACTORS`, shows up in `morphica list`, appears in the viewer dropdown, and always crashes without a usable error message.

---

### C-2 · `ZeroDivisionError` crash with `--points 0` in Voronoi  
**File:** `voronoi.py` line 277  
**Confirmed:** `python3 morphica.py voronoi --points 0` crashes with `ZeroDivisionError: division by zero`.

`lloyd_relax` computes `int(math.sqrt(width * height / len(pts)))` with no guard for `len(pts) == 0`. The `--points` argument accepts any integer (argparse minimum not set), so `--points 0` or negative values reach `lloyd_relax` with an empty list. The same path is taken for `--points 0` in `stipple` mode. Neither `render_voronoi` nor `lloyd_relax` validates the point count before using it as a divisor.

---

### C-3 · `voronoi_to_svg` crashes with IndexError when called with 0 points  
**File:** `voronoi.py` lines 382, 416  
**Confirmed:** `voronoi_to_svg([], 800, 800)` raises `IndexError: list index out of range`.

`hsv_cycle_palette(0)` returns `[]`. The inner loop initialises `best = 0` and then does `colors[best]` — `colors[0]` on an empty list. This is triggered by any code path that reaches `voronoi_to_svg` with zero points, which would include `--points 0` if the earlier lloyd_relax crash (C-2) were fixed.

---

## HIGH

### H-1 · Fortune's algorithm is entirely dead code and is also buggy  
**File:** `voronoi.py` lines 48–224 (the entire `fortune_voronoi` function)  
**Confirmed:** `render_voronoi` never calls `fortune_voronoi`. All rendering goes through `brute_voronoi_pixels` or `voronoi_to_svg`, both of which do their own brute-force nearest-neighbour sweep.

The function is ~175 lines advertised by the module docstring as "Fortune's sweep-line algorithm in O(n log n)". The actual output functions ignore it completely, so users always get O(w·h·n) brute-force regardless. The Fortune implementation itself contains at least two confirmed bugs:

- **Line 188:** `vx, vy = ev.y, ev.y` — both are set to `ev.y` (the circle-event y-coordinate). The circumcenter x-coordinate should be `ev.x` (the sweep position equals the circumcenter's rightmost extent, i.e. `ux + r`). If the recomputation block below (lines 193–202) is skipped (when `arc.prev` or `arc.next` is `None`), the fallback produces vertex `(vy, vy)` — a point whose x-coordinate is wrong.

- **Lines 168–169:** `add_edge(cur.site.idx, s.idx)` followed immediately by `add_edge(s.idx, cur.site.idx)` normalise to the same `(min, max)` key and hit the same slot. The second call is silently a no-op, so only one edge is created per split instead of two.

---

### H-2 · `voronoi_to_svg` produces a rasterised pseudo-SVG that is 14 MB for a default render  
**File:** `voronoi.py` lines 383–455  
**Confirmed:** A default 800×800 render with 80 points produces a ~14 MB SVG file.

`voronoi_to_svg` rasterises the diagram onto a `res × res` grid (where `res = min(width, height, 400)`, so 400 for any size ≥ 400), then emits one `<rect>` per grid cell — up to 160,000 `<rect>` elements — plus up to 160,000 `<line>` elements for edges. This defeats every advantage of SVG (scalability, editability, compact file size). A 14 MB SVG file for an 80-site Voronoi diagram is absurd; the correct approach is to output ~80 filled `<polygon>` elements. The format is advertised as "vector" via the `--format svg` flag but delivers a pixelated bitmap masquerading as SVG.

---

### H-3 · `reactiondiff.py` numpy path and pure-Python path produce different output for the same seed  
**File:** `reactiondiff.py` lines 119–134 vs 138–149  

The two code paths initialise noise differently:

- **numpy path (lines 128–133):** adds `rng.gauss(0, noise_level)` to *every* cell in both U and V grids, then clips.
- **pure-Python path (lines 144–148):** adds noise only inside the central patch, leaving the rest at exact `1.0` / `0.0`.

Same seed, same preset, same grid size → completely different simulation output depending on whether numpy is installed. This violates the documented `seed` reproducibility contract (which the code otherwise carefully upholds). The discrepancy is silent — there is no warning.

---

### H-4 · `_parse_hex_color` crashes on any non-6-digit hex string  
**File:** `lsystem.py` lines 357–359  
**Confirmed:** `_parse_hex_color('#abc')` raises `ValueError: invalid literal for int() with base 16: ''`. `_parse_hex_color('red')` raises `ValueError: invalid literal for int() with base 16: 're'`. `_parse_hex_color('#GGGGGG')` raises `ValueError`.

The function does zero validation. It is called with user-supplied `--color` and `--bg` CLI arguments (morphica.py lines 83, 351), so any malformed colour string produces an unhandled exception with a cryptic message rather than a useful CLI error. Short-form hex (`#rgb`), CSS named colours, and typos all crash identically.

---

## MEDIUM

### M-1 · Stochastic rule with all-zero weights silently selects the first production  
**File:** `lsystem.py` lines 121–131  
**Confirmed:** `rewrite('F', {'F': [(0.0, 'A'), (0.0, 'B')]}, 1)` returns `'A'`.

When all weights are zero, `total = 0` and `r = rng.random() * 0 = 0.0`. The first entry has `cumul = 0.0`, and `r <= cumul` (i.e. `0.0 <= 0.0`) is true, so the first production is always chosen. This produces deterministic output that appears stochastic to the author who wrote the rules. There is no validation that weights are positive or that they sum to a positive value.

---

### M-2 · `render_voronoi` in stipple mode performs a completely wasted lloyd relaxation  
**File:** `voronoi.py` lines 478–489  
**Confirmed by code inspection.**

When `stipple_mode=True`, `render_voronoi`:
1. Generates `n_points` random points from `rng`.
2. Calls `lloyd_relax` on those points — consuming O(iterations × grid_res²) time.
3. Discards the relaxed points entirely.
4. Calls `stipple(seed=seed)` which creates its own fresh `rng` from the original seed and generates a completely independent set of points.

The `lloyd_relax` call at line 480 does nothing useful in stipple mode. For 300 points with 5 Lloyd iterations, the wasted relaxation samples a ~100×100 grid 5 times = 5 million nearest-neighbour distance computations thrown away.

---

### M-3 · `lloyd_relax` accepts but silently ignores its `rng` parameter  
**File:** `voronoi.py` lines 264–295  

The function signature is `lloyd_relax(points, width, height, iterations=10, rng=None)`. The body never references `rng`. Lloyd relaxation is deterministic, so this is technically harmless, but the parameter creates a false impression that the caller can seed the relaxation step. All call sites pass `rng=rng` expecting it to matter. This is a documentation lie in the type signature.

---

### M-4 · `voronoi_to_svg` computes `scale_x` and `scale_y` but never uses them  
**File:** `voronoi.py` lines 386–387  

```python
scale_x = res / width * width   # simplifies to: res
scale_y = res / height * height  # simplifies to: res
```

Both expressions evaluate to `res` (the `width/height` cancel). Neither variable appears again in the function. This is dead code that, beyond wasting two assignments, actively misleads a reader who might think the scaling logic is correct when in fact the pixel-to-canvas coordinate mapping is done ad-hoc inline.

---

### M-5 · Attractor warmup steps are hidden from the user and cannot be overridden  
**File:** `attractors.py` lines 136–146, 244; `morphica.py` lines 411–415  

`render_attractor` always runs `cfg["warmup"]` iterations before the user's `--steps` count. For Lorenz, warmup is 1000. `python3 morphica.py attractor lorenz --steps 100` silently runs 1100 total orbit steps; the user's intent was 100. There is no `--warmup` CLI argument. No progress output distinguishes warmup from tracing. When the user passes a very small `--steps` value (e.g. 100) hoping for a quick preview, they pay the full warmup cost with no warning. This also means `--steps` does not represent the actual computation performed.

---

### M-6 · Interactive viewer silently degrades stochastic L-systems to deterministic  
**File:** `morphica.py` lines 291–296; `viewer.py` JS `growFrames` function  

When building the viewer's embedded L-system data, stochastic rules (list-valued rule entries) are silently collapsed to the first production only:

```python
if isinstance(v, list):   # stochastic → take first production
    rules[k] = v[0][1]
```

`stochastic_plant` has three equiprobable productions for `F`, but the viewer always uses `F[+F]F[-F]F`. The viewer then animates this deterministic expansion, giving no indication that the original preset is probabilistic. The UI has no control to trigger re-random generation. The `stochastic_plant` preset is completely misrepresented in the viewer.

---

### M-7 · `hsv_cycle_palette(n)` with `n=0` returns an empty list with no error  
**File:** `palette.py` lines 140–146  

`hsv_cycle_palette(0)` returns `[]`. This is a silent failure that only manifests as an `IndexError` at the first call site that tries to use a colour (as demonstrated in C-3). The function should raise `ValueError` for `n < 1` rather than returning an empty list that crashes downstream.

---

## LOW

### L-1 · Gray-Scott integration timestep `dt=1.0` is marginally unstable for larger diffusion coefficients  
**File:** `reactiondiff.py` line 52  

For the 5-point Laplacian with `h=1`, the von Neumann stability condition requires `dt * D * 4 < 1`. With `Du=0.19` (mitosis, fingerprint presets): `dt * Du * 4 = 0.76`. This is inside the stability bound but close. The condition is never checked or documented. A user adding a custom preset with `Du > 0.25` would silently get unstable (exploding or NaN) simulation output.

---

### L-2 · `paths_to_pixels` hardcodes line colour to white; `--color` flag is silently ignored for PNG output  
**File:** `lsystem.py` line 284  

```python
def draw_line(x0, y0, x1, y1, color=(255, 255, 255)):
```

The `color` parameter exists but `paths_to_pixels` never passes a colour to `draw_line`, so all lines are always white in PNG output regardless of the `--color` CLI flag. The SVG output correctly uses the `stroke` colour argument, so the same preset renders differently in PNG vs SVG mode. The `--color` flag is silently ignored for PNG output.

---

### L-3 · Fortune's algorithm site-event loop uses a shadow index (`si`) that can desync on duplicate x-coords  
**File:** `voronoi.py` lines 134–143  

The sweep loop pops events from `heap` (sorted by x) and, on non-circle events, consumes `pending_sites[si]` by index. This assumes the heap's site events fire in exactly the same order as `pending_sites`. Both are sorted by `(x, y)`, but they are independent data structures. If two sites share the same x-coordinate, heap ordering is determined by `_Event.__lt__` (which compares `(x, y)`), while pending_sites is sorted by `lambda s: s.x` — a stable sort that resolves ties differently from the `(x, y)` tuple comparison. This is moot since the function is dead code (H-1), but demonstrates the implementation is not production-ready.

---

### L-4 · Stochastic rule selection loop has no fallback if no production is selected  
**File:** `lsystem.py` lines 122–131  

The selection loop breaks on the first match and has no `else` clause:

```python
r = rng.random() * total
cumul = 0.0
for w, p in zip(weights, prods):
    cumul += w
    if r <= cumul:
        buf.append(p)
        break
```

If floating-point accumulation produces `cumul < total` at the last entry (possible with denormalised weights or non-summing float sequences), the character is silently dropped from the output — a non-deterministic string-shortening bug that would be extremely difficult to reproduce or diagnose.

---

### L-5 · `cmd_viewer` imports `rewrite` and `turtle_to_paths` from `lsystem` but never uses them  
**File:** `morphica.py` line 227  

```python
from lsystem import PRESETS as LSP, rewrite, turtle_to_paths
```

`rewrite` and `turtle_to_paths` are imported in `cmd_viewer` but are never called; the viewer uses `render_lsystem` instead. Dead import.

---

### L-6 · `voronoi_to_svg` SVG output size is O(res²) regardless of number of sites  
**File:** `voronoi.py` lines 383–455  
**Confirmed:** `voronoi_to_svg([(0.5,0.5)], 100, 100)` produces an 868 KB file.

Even with a single site, `voronoi_to_svg` still rasterises the full `res×res` grid and emits 160,000 `<rect>` elements. This is the same root cause as H-2 but also means that simplifying the algorithm (removing most sites) provides zero reduction in output file size.

---

### L-7 · `hilbert` L-system at 0 iterations produces a blank image with no warning  
**File:** `lsystem.py` line 341–345; `morphica.py` line 84  

The hilbert curve axiom is `"A"`, which is not a turtle drawing symbol. At 0 iterations no rewriting occurs, so `turtle_to_paths` sees only `"A"` and produces zero paths and the fallback bbox `(0, 0, 1, 1)`. The result is a solid-colour image with no content. No error or warning is emitted. Users who pass `--iterations 0` (intending to see the raw axiom) get a blank image silently. The same applies to `dragon` (axiom `FX`), `barnsley`, and `bush` (axiom `VZFFF`).

---

## Summary table

| ID  | Severity | File              | Lines      | Short description                                              |
|-----|----------|-------------------|------------|----------------------------------------------------------------|
| C-1 | CRITICAL | attractors.py     | 47–50, 205 | Duffing always crashes (OverflowError), parameters diverge    |
| C-2 | CRITICAL | voronoi.py        | 277        | `--points 0` → ZeroDivisionError in lloyd_relax               |
| C-3 | CRITICAL | voronoi.py        | 382, 416   | `voronoi_to_svg` IndexError with 0 points                     |
| H-1 | HIGH     | voronoi.py        | 48–224     | Fortune's algorithm is 175 lines of dead, buggy code          |
| H-2 | HIGH     | voronoi.py        | 383–455    | SVG is a rasterised bitmap: ~14 MB for 80 sites               |
| H-3 | HIGH     | reactiondiff.py   | 119–149    | numpy vs pure-Python paths give different output for same seed |
| H-4 | HIGH     | lsystem.py        | 357–359    | `_parse_hex_color` crashes on any non-6-digit hex input       |
| M-1 | MEDIUM   | lsystem.py        | 121–131    | Zero-weight stochastic rules silently pick first production   |
| M-2 | MEDIUM   | voronoi.py        | 478–489    | Lloyd relaxation wasted entirely in stipple_mode              |
| M-3 | MEDIUM   | voronoi.py        | 264        | `lloyd_relax` `rng` parameter accepted but silently ignored   |
| M-4 | MEDIUM   | voronoi.py        | 386–387    | `scale_x`/`scale_y` computed, never used, wrong formula       |
| M-5 | MEDIUM   | attractors.py     | 244; CLI   | Warmup steps hidden; `--steps` misrepresents actual work done |
| M-6 | MEDIUM   | morphica.py       | 291–296    | Viewer silently makes stochastic L-systems deterministic      |
| M-7 | MEDIUM   | palette.py        | 140–146    | `hsv_cycle_palette(0)` returns `[]` silently                  |
| L-1 | LOW      | reactiondiff.py   | 52         | dt=1.0 never validated; unstable for Du > 0.25                |
| L-2 | LOW      | lsystem.py        | 284        | PNG stroke colour hardcoded white; `--color` flag ignored     |
| L-3 | LOW      | voronoi.py        | 134–143    | Fortune site-index `si` can desync on duplicate x-coords      |
| L-4 | LOW      | lsystem.py        | 122–131    | Stochastic selection loop has no fallback if no branch fires  |
| L-5 | LOW      | morphica.py       | 227        | `rewrite`, `turtle_to_paths` imported in cmd_viewer, unused   |
| L-6 | LOW      | voronoi.py        | 383–455    | SVG file size O(res²) independent of site count               |
| L-7 | LOW      | lsystem.py        | 341–345    | 0-iteration render of axiom-only presets produces blank image |
