#!/usr/bin/env python3
"""
Morphica test suite — exercises all features.

Run: python3 -m pytest tests/ -v
  or: python3 tests/test_morphica.py
"""
import sys
import os
import math
import random
import unittest
import struct
import zlib

# Make sure local modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from palette import sample_palette, apply_palette, hsv_cycle_palette, PALETTE_NAMES
from png_encoder import encode_png, save_png
from lsystem import (rewrite, turtle_to_paths, paths_to_svg, paths_to_pixels,
                     render_lsystem, PRESETS as LS_PRESETS)
from reactiondiff import simulate, field_to_pixels, PRESETS as RD_PRESETS
from attractors import render_attractor, ATTRACTORS
from voronoi import (brute_voronoi_pixels, lloyd_relax, stipple,
                     voronoi_to_svg, render_voronoi)
from animate import animate_lsystem, animate_attractor


# ── Palette tests ─────────────────────────────────────────────────────────────

class TestPalette(unittest.TestCase):
    def test_all_palettes_return_valid_rgb(self):
        for name in PALETTE_NAMES:
            for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
                r, g, b = sample_palette(name, t)
                self.assertIsInstance(r, int)
                self.assertGreaterEqual(r, 0); self.assertLessEqual(r, 255)
                self.assertGreaterEqual(g, 0); self.assertLessEqual(g, 255)
                self.assertGreaterEqual(b, 0); self.assertLessEqual(b, 255)

    def test_palette_clamping(self):
        # Values outside [0,1] should clamp gracefully
        r, g, b = sample_palette("viridis", -0.5)
        r2, g2, b2 = sample_palette("viridis", 0.0)
        self.assertEqual((r, g, b), (r2, g2, b2))
        r3, g3, b3 = sample_palette("viridis", 1.5)
        r4, g4, b4 = sample_palette("viridis", 1.0)
        self.assertEqual((r3, g3, b3), (r4, g4, b4))

    def test_unknown_palette_raises(self):
        with self.assertRaises(ValueError):
            sample_palette("nonexistent", 0.5)

    def test_apply_palette(self):
        vals = [0.0, 0.5, 1.0]
        result = apply_palette(vals, "fire")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], sample_palette("fire", 0.0))
        self.assertEqual(result[-1], sample_palette("fire", 1.0))

    def test_hsv_cycle_palette(self):
        colors = hsv_cycle_palette(5)
        self.assertEqual(len(colors), 5)
        # All distinct hues (different colours)
        self.assertTrue(len(set(colors)) > 1)

    def test_hsv_cycle_single(self):
        colors = hsv_cycle_palette(1)
        self.assertEqual(len(colors), 1)

    def test_12_palettes_present(self):
        self.assertGreaterEqual(len(PALETTE_NAMES), 12)


# ── PNG encoder tests ─────────────────────────────────────────────────────────

def _decode_png(data):
    """Simple PNG decoder for testing (handles Sub filter only)."""
    # Parse IHDR
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    channels = None
    width = height = 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        tag = data[pos+4:pos+8]
        chunk = data[pos+8:pos+8+length]
        if tag == b"IHDR":
            width, height, depth, colortype = struct.unpack(">IIBB", chunk[:10])
            channels = 4 if colortype == 6 else 3
        elif tag == b"IDAT":
            raw = zlib.decompress(chunk)
            bpp = channels
            row_len = 1 + width * bpp
            result = []
            for row in range(height):
                base = row * row_len
                ftype = raw[base]
                assert ftype == 1, f"Expected Sub filter, got {ftype}"
                prev = [0] * bpp
                for col in range(width):
                    vals = []
                    for ch in range(bpp):
                        recon = (raw[base + 1 + col*bpp + ch] + prev[ch]) & 0xFF
                        vals.append(recon)
                    prev = list(vals)
                    result.append(tuple(vals[:3]))  # strip alpha
            return result, width, height
        pos += 4 + 4 + length + 4  # length + tag + data + crc
    return [], width, height


class TestPNGEncoder(unittest.TestCase):
    def test_round_trip_rgb(self):
        w, h = 10, 8
        rng = random.Random(42)
        pixels = [(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
                  for _ in range(w * h)]
        data = encode_png(w, h, pixels, mode="RGB")
        decoded, dw, dh = _decode_png(data)
        self.assertEqual(dw, w)
        self.assertEqual(dh, h)
        self.assertEqual(len(decoded), w * h)
        for i, (orig, dec) in enumerate(zip(pixels, decoded)):
            self.assertEqual(orig, dec, f"Pixel {i} mismatch")

    def test_channel_clamping(self):
        # Out-of-range values should clamp via & 0xFF
        pixels = [(256, 300, 400)]
        data = encode_png(1, 1, pixels, mode="RGB")
        decoded, _, _ = _decode_png(data)
        # 256 & 0xFF = 0, 300 & 0xFF = 44, 400 & 0xFF = 144
        self.assertEqual(decoded[0], (0, 44, 144))

    def test_png_magic_bytes(self):
        data = encode_png(1, 1, [(128, 128, 128)])
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    def test_png_has_iend(self):
        data = encode_png(2, 2, [(0, 0, 0)] * 4)
        self.assertTrue(data.endswith(b"IEND\xaeB`\x82"))

    def test_all_black(self):
        data = encode_png(4, 4, [(0, 0, 0)] * 16)
        decoded, w, h = _decode_png(data)
        self.assertTrue(all(p == (0, 0, 0) for p in decoded))

    def test_all_white(self):
        data = encode_png(3, 3, [(255, 255, 255)] * 9)
        decoded, _, _ = _decode_png(data)
        self.assertTrue(all(p == (255, 255, 255) for p in decoded))

    def test_rgba_mode(self):
        pixels = [(100, 150, 200, 255), (50, 75, 100, 128)]
        data = encode_png(2, 1, pixels, mode="RGBA")
        # Just check it doesn't crash and has correct header
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")


# ── L-system tests ────────────────────────────────────────────────────────────

class TestLSystem(unittest.TestCase):
    def test_rewrite_simple(self):
        result = rewrite("F", {"F": "F+F"}, 2)
        self.assertEqual(result, "F+F+F+F")

    def test_rewrite_0_iterations(self):
        result = rewrite("ABC", {"A": "X"}, 0)
        self.assertEqual(result, "ABC")

    def test_rewrite_stochastic_seed_reproducible(self):
        rules = {"F": [(0.5, "F+F"), (0.5, "F-F")]}
        r1 = rewrite("FFF", rules, 3, rng=random.Random(42))
        r2 = rewrite("FFF", rules, 3, rng=random.Random(42))
        self.assertEqual(r1, r2)

    def test_rewrite_stochastic_different_seeds(self):
        rules = {"F": [(0.5, "F+F"), (0.5, "F-F")]}
        r1 = rewrite("FFF", rules, 3, rng=random.Random(1))
        r2 = rewrite("FFF", rules, 3, rng=random.Random(2))
        # With different seeds, most likely different (not guaranteed but very probable)
        # We just test they are valid strings
        self.assertIsInstance(r1, str)
        self.assertIsInstance(r2, str)

    def test_turtle_empty_string(self):
        paths, bbox = turtle_to_paths("", 90, 5.0)
        self.assertEqual(paths, [])

    def test_turtle_forward_only(self):
        paths, bbox = turtle_to_paths("FFF", 90, 1.0)
        self.assertEqual(len(paths), 1)
        # Should have 4 points (start + 3 moves)
        self.assertEqual(len(paths[0]), 4)

    def test_turtle_branch_and_return(self):
        paths, bbox = turtle_to_paths("F[+F][-F]", 90, 5.0)
        # Should produce multiple paths
        self.assertGreater(len(paths), 1)

    def test_turtle_bbox_sensible(self):
        paths, bbox = turtle_to_paths("F+F+F+F", 90, 10.0)
        bx0, by0, bx1, by1 = bbox
        self.assertLess(bx0, bx1)
        self.assertLess(by0, by1)

    def test_all_presets_render_svg(self):
        for name in LS_PRESETS:
            svg = render_lsystem(name, output_format="svg", seed=0)
            self.assertIsInstance(svg, str)
            self.assertIn("<svg", svg)
            self.assertIn("</svg>", svg)

    def test_all_presets_render_pixels(self):
        for name in LS_PRESETS:
            pixels, w, h = render_lsystem(name, width=100, height=100,
                                           output_format="pixels", seed=0)
            self.assertEqual(len(pixels), 100 * 100)

    def test_seed_reproducibility(self):
        p1, w1, h1 = render_lsystem("stochastic_plant", output_format="pixels",
                                     width=100, height=100, seed=42)
        p2, w2, h2 = render_lsystem("stochastic_plant", output_format="pixels",
                                     width=100, height=100, seed=42)
        self.assertEqual(p1, p2)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            render_lsystem("nonexistent_preset")

    def test_hex_shorthand_color(self):
        # 3-char hex should not raise
        pixels, w, h = render_lsystem("koch", width=50, height=50,
                                       output_format="pixels", bg="#000", stroke="#fff")
        self.assertEqual(len(pixels), 50 * 50)

    def test_0_iterations_produces_image(self):
        pixels, w, h = render_lsystem("koch", iterations=0,
                                       output_format="pixels", width=50, height=50)
        self.assertEqual(len(pixels), 50 * 50)


# ── Reaction-diffusion tests ──────────────────────────────────────────────────

class TestReactionDiffusion(unittest.TestCase):
    def test_all_presets_run(self):
        for name in RD_PRESETS:
            v, w, h = simulate(preset_name=name, width=30, height=30,
                                steps=100, seed=0)
            self.assertEqual(len(v), 30 * 30)
            self.assertTrue(all(math.isfinite(x) for x in v))

    def test_output_range(self):
        v, w, h = simulate(preset_name="spots", width=40, height=40,
                            steps=200, seed=42)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in v), "V out of [0,1]")

    def test_seed_reproducibility(self):
        v1, _, _ = simulate(preset_name="coral", width=30, height=30,
                             steps=50, seed=7)
        v2, _, _ = simulate(preset_name="coral", width=30, height=30,
                             steps=50, seed=7)
        self.assertEqual(v1, v2)

    def test_different_seeds_differ(self):
        v1, _, _ = simulate(preset_name="worms", width=30, height=30,
                             steps=50, seed=1)
        v2, _, _ = simulate(preset_name="worms", width=30, height=30,
                             steps=50, seed=2)
        self.assertNotEqual(v1, v2)

    def test_field_to_pixels(self):
        v = [0.0, 0.25, 0.5, 0.75, 1.0]
        from palette import PALETTES
        pfn = PALETTES["viridis"]
        pixels = field_to_pixels(v, 5, 1, pfn)
        self.assertEqual(len(pixels), 5)
        for p in pixels:
            r, g, b = p
            self.assertGreaterEqual(r, 0); self.assertLessEqual(r, 255)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            simulate(preset_name="not_a_preset")

    def test_pattern_evolves_from_initial(self):
        # After many steps, the field should differ from an all-zeros state
        v, _, _ = simulate(preset_name="maze", width=40, height=40,
                            steps=500, seed=3)
        # The V field should not be constant
        self.assertGreater(max(v) - min(v), 0.01)


# ── Attractor tests ───────────────────────────────────────────────────────────

class TestAttractors(unittest.TestCase):
    def test_all_attractors_render(self):
        from palette import PALETTES
        pfn = PALETTES["plasma"]
        for name in ATTRACTORS:
            pixels, w, h = render_attractor(name, width=80, height=80,
                                             steps=5000, seed=42, palette_fn=pfn)
            self.assertEqual(len(pixels), 80 * 80)
            bg = (10, 10, 10)
            non_bg = sum(1 for p in pixels if p != bg)
            self.assertGreater(non_bg, 0, f"{name} attractor produced empty image")

    def test_histogram_density_coloring(self):
        # High-density pixels should be different colour from low-density ones
        from palette import PALETTES
        pfn = PALETTES["fire"]
        pixels, w, h = render_attractor("clifford", width=200, height=200,
                                         steps=200000, seed=0, palette_fn=pfn)
        unique_colors = set(pixels)
        # Multiple density levels should yield multiple unique colors
        self.assertGreater(len(unique_colors), 5)

    def test_seed_reproducibility(self):
        from palette import PALETTES
        pfn = PALETTES["plasma"]
        p1, _, _ = render_attractor("lorenz", width=50, height=50,
                                     steps=10000, seed=99, palette_fn=pfn)
        p2, _, _ = render_attractor("lorenz", width=50, height=50,
                                     steps=10000, seed=99, palette_fn=pfn)
        self.assertEqual(p1, p2)

    def test_duffing_no_overflow(self):
        # Regression: duffing used to raise OverflowError
        from palette import PALETTES
        pfn = PALETTES["neon"]
        pixels, w, h = render_attractor("duffing", width=60, height=60,
                                         steps=5000, seed=42, palette_fn=pfn)
        self.assertEqual(len(pixels), 60 * 60)

    def test_unknown_attractor_raises(self):
        with self.assertRaises(ValueError):
            render_attractor("nonexistent")


# ── Voronoi tests ─────────────────────────────────────────────────────────────

class TestVoronoi(unittest.TestCase):
    def test_brute_voronoi_single_point(self):
        pixels, w, h = brute_voronoi_pixels([(0.5, 0.5)], 20, 20)
        # All pixels should have the same colour (one cell)
        self.assertTrue(all(p == pixels[0] for p in pixels))

    def test_brute_voronoi_zero_points(self):
        pixels, w, h = brute_voronoi_pixels([], 10, 10)
        bg = (10, 10, 10)
        self.assertTrue(all(p == bg for p in pixels))

    def test_voronoi_coverage(self):
        # Each site should "own" at least one pixel
        pts = [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)]
        pixels, w, h = brute_voronoi_pixels(pts, 30, 30)
        from palette import hsv_cycle_palette
        colors = hsv_cycle_palette(3)
        for color in colors:
            self.assertIn(color, pixels, f"Color {color} not found in Voronoi")

    def test_lloyd_relax_convergence(self):
        rng = random.Random(1)
        pts = [(rng.random(), rng.random()) for _ in range(10)]
        relaxed = lloyd_relax(pts, 100, 100, iterations=5)
        self.assertEqual(len(relaxed), 10)
        # All points should remain in [0,1]
        for x, y in relaxed:
            self.assertGreaterEqual(x, 0.0); self.assertLessEqual(x, 1.0)
            self.assertGreaterEqual(y, 0.0); self.assertLessEqual(y, 1.0)

    def test_lloyd_empty_list(self):
        result = lloyd_relax([], 100, 100, iterations=3)
        self.assertEqual(result, [])

    def test_stipple_point_count(self):
        pixels, w, h, pts = stipple(20, 100, 100, seed=42, lloyd_iters=1)
        self.assertEqual(len(pts), 20)
        self.assertEqual(len(pixels), 100 * 100)

    def test_voronoi_svg_valid(self):
        pts = [(0.2, 0.3), (0.7, 0.8), (0.5, 0.1)]
        svg = voronoi_to_svg(pts, 200, 200)
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)

    def test_voronoi_svg_empty(self):
        svg = voronoi_to_svg([], 100, 100)
        self.assertIn("<svg", svg)

    def test_render_voronoi_zero_points_raises(self):
        with self.assertRaises(ValueError):
            render_voronoi(n_points=0)

    def test_render_voronoi_pixels(self):
        pixels, w, h = render_voronoi(n_points=10, width=50, height=50,
                                       seed=1, output_format="pixels")
        self.assertEqual(len(pixels), 50 * 50)

    def test_stipple_mode(self):
        pixels, w, h = render_voronoi(n_points=15, width=80, height=80,
                                       seed=7, stipple_mode=True)
        self.assertEqual(len(pixels), 80 * 80)

    def test_seed_reproducibility(self):
        r1 = render_voronoi(n_points=20, width=50, height=50, seed=5, output_format="pixels")
        r2 = render_voronoi(n_points=20, width=50, height=50, seed=5, output_format="pixels")
        self.assertEqual(r1, r2)


# ── Animation tests ───────────────────────────────────────────────────────────

class TestAnimate(unittest.TestCase):
    def setUp(self):
        self.out = os.path.join(os.path.dirname(__file__), "..", "output", "test_anim")
        os.makedirs(self.out, exist_ok=True)

    def test_lsystem_frames(self):
        out_dir = os.path.join(self.out, "lsys")
        files = animate_lsystem("dragon", max_iter=3, width=80, height=80,
                                 output_dir=out_dir, seed=0, verbose=False)
        self.assertEqual(len(files), 4)  # iter 0,1,2,3
        for f in files:
            self.assertTrue(os.path.exists(f), f"Frame missing: {f}")
            self.assertGreater(os.path.getsize(f), 100)

    def test_attractor_frames(self):
        out_dir = os.path.join(self.out, "att")
        files = animate_attractor("dejong", total_steps=5000, n_frames=3,
                                   width=60, height=60, output_dir=out_dir,
                                   seed=42, verbose=False)
        self.assertEqual(len(files), 3)
        for f in files:
            self.assertTrue(os.path.exists(f))

    def test_frames_are_valid_png(self):
        out_dir = os.path.join(self.out, "pngcheck")
        files = animate_lsystem("koch", max_iter=2, width=60, height=60,
                                 output_dir=out_dir, seed=1, verbose=False)
        for f in files:
            with open(f, "rb") as fp:
                magic = fp.read(8)
            self.assertEqual(magic, b"\x89PNG\r\n\x1a\n", f"Not a valid PNG: {f}")


# ── Integration tests ─────────────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):
    def test_rd_then_palette_cycle(self):
        from animate import animate_palette_cycle
        v, w, h = simulate(preset_name="spots", width=50, height=50, steps=200, seed=11)
        out_dir = os.path.join(os.path.dirname(__file__), "..", "output", "test_anim", "palcyc")
        files = animate_palette_cycle(v, w, h, n_frames=4, output_dir=out_dir, verbose=False)
        self.assertEqual(len(files), 4)
        for f in files:
            self.assertTrue(os.path.exists(f))

    def test_full_pipeline_lsystem_png(self):
        from png_encoder import encode_png
        pixels, w, h = render_lsystem("sierpinski", iterations=4,
                                       width=80, height=80, output_format="pixels",
                                       seed=5)
        data = encode_png(w, h, pixels)
        decoded, dw, dh = _decode_png(data)
        self.assertEqual(dw, w)
        self.assertEqual(dh, h)
        # At least one non-background pixel
        bg = (17, 17, 17)
        non_bg = sum(1 for p in decoded if p != bg)
        self.assertGreater(non_bg, 0)

    def test_full_pipeline_attractor_png(self):
        from png_encoder import encode_png
        from palette import PALETTES
        pixels, w, h = render_attractor("rossler", width=80, height=80,
                                         steps=10000, seed=0,
                                         palette_fn=PALETTES["sunset"])
        data = encode_png(w, h, pixels)
        decoded, dw, dh = _decode_png(data)
        self.assertEqual(dw, w)
        bg = (10, 10, 10)
        non_bg = sum(1 for p in decoded if p != bg)
        self.assertGreater(non_bg, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
