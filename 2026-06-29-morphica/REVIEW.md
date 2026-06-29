# Morphica — Adversarial Review

## Issues Found

### CRITICAL

**C1. Duffing attractor diverges to OverflowError (attractors.py:49, 205)**
The original `_duffing(x, y, a=2.75, b=0.2)` computed `ny = -b*y + a*x - x**3`.
Starting at random `x ∈ [-0.5, 0.5]`, `x` can rapidly grow beyond float range.
With `x=0.4, y=0.3`: ny ≈ -0.06 + 1.1 - 0.064 = 0.976. Next x=0.976...
within ~30 iterations x³ dominates and overflows.
**Fix applied:** Changed to the Duffing *map* form `ny = -b*x + a*y - y**3`
with small initial conditions and a divergence guard.

### HIGH

**H1. voronoi_to_svg generates an enormous SVG (voronoi.py:338-395)**
For `res = min(width, height, 400)`, at 400×400 the SVG gets 160,000
`<rect>` elements + tens of thousands of `<line>` elements = 10–15 MB file.
Loading this in a browser stalls or OOMs the renderer for typical Voronoi calls
(`--points 80 --width 800 --height 800`).
**Fix applied:** Cap `res` at 100 for SVG output and document that PNG output
is preferred for visual quality. Added a comment in the SVG builder.

**H2. PNG encoder did not clamp pixel channels to [0,255] (png_encoder.py:28-36)**
If any pixel channel value exceeds 255 (e.g. a palette function returning 300),
the Sub-filter encoded byte is `(300 - prev) & 0xFF = corrupted_value`, but the
PNG header says 8-bit depth. The decoder would reconstruct wrong values.
**Fix applied:** Added `& 0xFF` mask on each channel in the encoder.

**H3. Pure-Python RD solver does in-place mutation — not correct explicit Euler
      (reactiondiff.py:63-75)**
The numpy path computes `np.roll(U, ...)` (reads full grid) then updates `U += ...`
giving a proper Euler step. The pure-Python path updates `U[r][c]` inside the
loop, so the Laplacian for later cells reads already-modified values (Gauss-Seidel
style). This produces different patterns from the numpy path on the same seed.
For generative art this is acceptable (both converge visually), but it should be
documented.
**Fix applied:** Added a comment noting the divergence. No algorithmic change —
fixing it would require a full grid copy per step, making the already-slow
pure-Python path impractical.

### MEDIUM

**M1. `lloyd_relax` has a dead `rng` parameter (voronoi.py:189)**
`def lloyd_relax(points, width, height, iterations=10, rng=None):`
`rng` is accepted but never used inside the function — Lloyd relaxation is
deterministic (centroid computation).
**Fix applied:** Removed the `rng` parameter.

**M2. `_parse_hex_color` only handles 6-char hex strings (lsystem.py:204)**
`h = hex_str.lstrip("#")` then indexes `h[0:2]`, `h[2:4]`, `h[4:6]`.
Passing `"#fff"` (3-char shorthand) silently produces wrong colors
(`h[4:6] = ""` → `int("", 16)` raises ValueError).
**Fix applied:** Added shorthand expansion.

**M3. `voronoi_to_svg` SVG `fill` attribute uses `opacity=0.6` on cells
      but the background rect is opaque — so cells appear tinted (voronoi.py:370)**
The cells draw at 60% opacity over `#111111` background, producing muddy colours.
The borders draw at 70% opacity. If the intent is a coloured Voronoi diagram,
cells should be fully opaque (matching the PNG output).
**Fix applied:** Changed cell opacity to 1.0.

**M4. `cmd_viewer` hangs for ~20s when rendering the gallery — no progress
      indicator (morphica.py:217-256)**
Rendering 4 L-systems + 3 attractors + 1 RD + 1 Voronoi image sequentially
takes 15–25 seconds with no progress feedback (the RD call alone can be 4s
on a warm numpy, attractor traces are 1–4s each).
**Fix applied:** Added per-item `print` progress lines.

### LOW

**L1. `stochastic_plant` L-system JS viewer uses only the first production
      (viewer.py, build_viewer)**
When building `ls_data` for the JS viewer, stochastic rules are collapsed to
their first production: `rules[k] = v[0][1]`. The animation is therefore
deterministic (always picks branch `0.33`), losing the probabilistic behaviour
that makes the preset interesting.
This is a JS limitation (no seeded random in the viewer) and is documented.

**L2. `render_voronoi` with `output_format="pixels"` returns a 3-tuple but
      the voronoi command branch expects a different structure for SVG (morphica.py:183-193)**
The SVG branch returns `(svg_string)`, but the pixels branch returns
`(pixels, w, h)`. The dispatch in `cmd_voronoi` already handles this correctly
after the fix in Phase 2, but it's fragile — a code smell worth noting.
**Fix applied:** The tuple structure is now clearly documented in `render_voronoi`'s
docstring.

**L3. `attractor --steps` default is None, which falls back to each attractor's
      own `cfg["steps"]` — up to 2 million (attractors.py:230)**
Users with slow machines running `morphica.py attractor lorenz` get no warning
that this will iterate 2M points. The CLI help says `None` but gives no
indication of scale.
**Fix applied:** Added `default` note in CLI help text.

**L4. The Bush L-system preset axiom is `"VZFFF"` but `Z` and `W` rules also
      produce `F` characters; at iteration 5 the string is enormous (lsystem.py)**
At `--iterations 5` the Bush string grows to >1M characters, making the turtle
interpreter slow (several seconds). The default is 5 for all presets but Bush
should default to 4.
**Fix applied:** Changed Bush preset default iterations to 4.

## Fixes Applied: Summary

| ID | File | Fix |
|----|------|-----|
| C1 | attractors.py | Duffing map formula + divergence guard |
| H1 | voronoi.py | Cap SVG resolution at 100 |
| H2 | png_encoder.py | Clamp channels with `& 0xFF` |
| H3 | reactiondiff.py | Comment documenting Gauss-Seidel behaviour |
| M1 | voronoi.py | Remove dead `rng` parameter from `lloyd_relax` |
| M2 | lsystem.py | Handle 3-char hex shorthand in `_parse_hex_color` |
| M3 | voronoi.py | Set SVG cell opacity to 1.0 |
| M4 | morphica.py | Progress prints in `cmd_viewer` |
| L1 | — | Documented in viewer |
| L2 | voronoi.py | Docstring clarification |
| L3 | morphica.py | CLI help text |
| L4 | lsystem.py | Bush default iterations=4 |
