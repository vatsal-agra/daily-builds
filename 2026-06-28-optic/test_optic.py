#!/usr/bin/env python3
"""
test_optic.py — Test suite for Optic computer vision library.
Run with: python3 test_optic.py [-v]
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import optic
from optic import (
    Image, decode_png, encode_png, read_png, write_png,
    gaussian_blur, convolve2d, sobel, prewitt, scharr, canny,
    harris_corners, fast_corners,
    dilate, erode, opening, closing, morph_gradient, top_hat, black_hat, hit_or_miss,
    connected_components, colorize_labels, make_se,
    threshold_otsu, threshold_adaptive,
    hough_lines, draw_lines,
    template_match_ncc, find_matches,
    bilateral_filter,
    make_checkerboard, make_shapes, make_circles, make_lines_image,
    draw_corners, build_pipeline_html,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flat_img(w, h, mode='L', v=0.5):
    img = Image(w, h, mode, fill=v)
    return img


def _max_diff(a: Image, b: Image) -> float:
    assert a.mode == b.mode and a.width == b.width and a.height == b.height
    d = 0.0
    for p1, p2 in zip(a.planes, b.planes):
        d = max(d, max(abs(x - y) for x, y in zip(p1, p2)))
    return d


# ─────────────────────────────────────────────────────────────────────────────
# PNG I/O tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPngIO(unittest.TestCase):

    def _make_gradient(self, w, h, mode):
        nc = {'L': 1, 'RGB': 3, 'RGBA': 4, 'LA': 2}[mode]
        img = Image(w, h, mode)
        n = w * h
        for ch in range(nc):
            img.planes[ch] = [(ch * n + i) / (nc * n) for i in range(n)]
        return img

    def test_roundtrip_L(self):
        img = self._make_gradient(31, 17, 'L')
        d = _max_diff(img, decode_png(encode_png(img)))
        self.assertLess(d, 1 / 255.0 + 1e-9)

    def test_roundtrip_RGB(self):
        img = self._make_gradient(23, 29, 'RGB')
        d = _max_diff(img, decode_png(encode_png(img)))
        self.assertLess(d, 1 / 255.0 + 1e-9)

    def test_roundtrip_RGBA(self):
        img = self._make_gradient(13, 19, 'RGBA')
        d = _max_diff(img, decode_png(encode_png(img)))
        self.assertLess(d, 1 / 255.0 + 1e-9)

    def test_roundtrip_LA(self):
        img = self._make_gradient(11, 7, 'LA')
        d = _max_diff(img, decode_png(encode_png(img)))
        self.assertLess(d, 1 / 255.0 + 1e-9)

    def test_1x1_image(self):
        img = Image(1, 1, 'RGB')
        img.planes[0][0] = 0.5; img.planes[1][0] = 0.25; img.planes[2][0] = 0.75
        img2 = decode_png(encode_png(img))
        self.assertAlmostEqual(img2.planes[0][0], 0.5, delta=1/255)
        self.assertAlmostEqual(img2.planes[1][0], 0.25, delta=1/255)
        self.assertAlmostEqual(img2.planes[2][0], 0.75, delta=1/255)

    def test_large_image_roundtrip(self):
        img = self._make_gradient(200, 150, 'RGB')
        d = _max_diff(img, decode_png(encode_png(img)))
        self.assertLess(d, 1 / 255.0 + 1e-9)

    def test_bad_signature_raises(self):
        with self.assertRaises(ValueError):
            decode_png(b'not a png')

    def test_crc_error_raises(self):
        data = encode_png(Image(4, 4, 'L', fill=0.5))
        corrupted = bytearray(data)
        corrupted[30] ^= 0xFF   # flip a byte in IHDR CRC
        with self.assertRaises(ValueError):
            decode_png(bytes(corrupted))

    def test_write_creates_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            path = f.name
        try:
            write_png(Image(10, 10, 'L', fill=0.3), path)
            self.assertTrue(os.path.exists(path))
            img2 = read_png(path)
            self.assertEqual(img2.width, 10)
            self.assertEqual(img2.mode, 'L')
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────────────
# Image operations
# ─────────────────────────────────────────────────────────────────────────────

class TestImageOps(unittest.TestCase):

    def test_grayscale_from_rgb(self):
        img = Image(4, 4, 'RGB')
        img.planes[0] = [1.0] * 16  # pure red
        img.planes[1] = [0.0] * 16
        img.planes[2] = [0.0] * 16
        gray = img.grayscale()
        self.assertEqual(gray.mode, 'L')
        self.assertAlmostEqual(gray.planes[0][0], 0.2126, delta=1e-4)

    def test_grayscale_already_L(self):
        img = Image(5, 5, 'L', fill=0.7)
        g = img.grayscale()
        self.assertEqual(g.mode, 'L')
        self.assertEqual(g.planes[0][0], 0.7)

    def test_to_rgb_from_L(self):
        img = Image(3, 3, 'L', fill=0.4)
        rgb = img.to_rgb()
        self.assertEqual(rgb.mode, 'RGB')
        self.assertAlmostEqual(rgb.planes[0][0], 0.4)
        self.assertAlmostEqual(rgb.planes[1][0], 0.4)
        self.assertAlmostEqual(rgb.planes[2][0], 0.4)

    def test_flip_h_involution(self):
        img = make_shapes(32, 32)
        self.assertLess(_max_diff(img, img.flip_h().flip_h()), 1e-12)

    def test_flip_v_involution(self):
        img = make_shapes(32, 32)
        self.assertLess(_max_diff(img, img.flip_v().flip_v()), 1e-12)

    def test_crop_restore(self):
        img = make_shapes(64, 64)
        cropped = img.crop(10, 5, 30, 20)
        self.assertEqual(cropped.width, 30)
        self.assertEqual(cropped.height, 20)
        # Value at (0,0) of crop == value at (5, 10) of original
        self.assertAlmostEqual(cropped.planes[0][0], img.planes[0][5 * 64 + 10], delta=1e-9)

    def test_resize_nearest_size(self):
        img = Image(64, 64, 'L', fill=0.5)
        r = img.resize_nearest(32, 48)
        self.assertEqual(r.width, 32)
        self.assertEqual(r.height, 48)

    def test_resize_bilinear_constant(self):
        img = Image(10, 10, 'L', fill=0.6)
        r = img.resize_bilinear(20, 20)
        # Uniform image: all output values should be 0.6
        self.assertAlmostEqual(max(r.planes[0]), 0.6, delta=1e-6)
        self.assertAlmostEqual(min(r.planes[0]), 0.6, delta=1e-6)

    def test_rotate_0_unchanged(self):
        img = make_shapes(32, 32)
        rotated = img.rotate(0.0)
        self.assertLess(_max_diff(img, rotated), 1e-9)

    def test_rotate_360_near_unchanged(self):
        img = make_shapes(64, 64)
        rotated = img.rotate(360.0)
        self.assertLess(_max_diff(img, rotated), 1e-9)

    def test_normalize_range(self):
        img = Image(5, 5, 'L')
        img.planes[0] = [float(i) for i in range(25)]
        n = img.normalize()
        self.assertAlmostEqual(min(n.planes[0]), 0.0, delta=1e-9)
        self.assertAlmostEqual(max(n.planes[0]), 1.0, delta=1e-9)

    def test_brightness(self):
        img = Image(4, 4, 'L', fill=0.5)
        bright = img.adjust_brightness(2.0)
        self.assertAlmostEqual(bright.planes[0][0], 1.0)  # clamped at 1

    def test_blend(self):
        a = Image(4, 4, 'L', fill=0.0)
        b = Image(4, 4, 'L', fill=1.0)
        c = a.blend(b, 0.5)
        self.assertAlmostEqual(c.planes[0][0], 0.5, delta=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Filtering / edge detection
# ─────────────────────────────────────────────────────────────────────────────

class TestFilters(unittest.TestCase):

    def test_gaussian_sum_preservation(self):
        """Gaussian blur must preserve the total image intensity (sum)."""
        import random; rng = random.Random(1)
        img = Image(32, 32, 'L')
        img.planes[0] = [rng.random() for _ in range(32 * 32)]
        blurred = gaussian_blur(img, sigma=1.5)
        s1 = sum(img.planes[0])
        s2 = sum(blurred.planes[0])
        self.assertAlmostEqual(s1, s2, delta=s1 * 0.002)

    def test_gaussian_constant_image(self):
        """Blurring a constant image returns the same constant."""
        img = Image(20, 20, 'L', fill=0.7)
        blurred = gaussian_blur(img, sigma=2.0)
        self.assertAlmostEqual(max(blurred.planes[0]), 0.7, delta=1e-4)
        self.assertAlmostEqual(min(blurred.planes[0]), 0.7, delta=1e-4)

    def test_gaussian_rgb(self):
        """Gaussian blur on RGB should work channel-independently."""
        img = Image(16, 16, 'RGB', fill=0.5)
        blurred = gaussian_blur(img, sigma=1.0)
        self.assertEqual(blurred.mode, 'RGB')

    def test_sobel_vertical_step_edge(self):
        """Step edge along x → large Gx, near-zero Gy."""
        img = Image(20, 20, 'L')
        for r in range(20):
            for c in range(20):
                img.planes[0][r * 20 + c] = 1.0 if c >= 10 else 0.0
        gx, gy, mag, _ = sobel(img)
        # Max Gx near column 10
        max_gx = max(abs(gx.planes[0][r * 20 + c]) for r in range(1, 19) for c in range(8, 12))
        max_gy = max(abs(gy.planes[0][r * 20 + c]) for r in range(1, 19) for c in range(8, 12))
        self.assertGreater(max_gx, max_gy * 4)

    def test_sobel_horizontal_step_edge(self):
        """Step edge along y → large Gy, near-zero Gx."""
        img = Image(20, 20, 'L')
        for r in range(20):
            for c in range(20):
                img.planes[0][r * 20 + c] = 1.0 if r >= 10 else 0.0
        gx, gy, mag, _ = sobel(img)
        max_gx = max(abs(gx.planes[0][r * 20 + c]) for r in range(8, 12) for c in range(1, 19))
        max_gy = max(abs(gy.planes[0][r * 20 + c]) for r in range(8, 12) for c in range(1, 19))
        self.assertGreater(max_gy, max_gx * 4)

    def test_sobel_flat_image_zero_gradient(self):
        img = Image(16, 16, 'L', fill=0.5)
        gx, gy, mag, _ = sobel(img)
        self.assertAlmostEqual(max(abs(v) for v in mag.planes[0]), 0.0, delta=1e-9)

    def test_prewitt_detects_edges(self):
        img = make_shapes(32, 32)
        _, _, mag, _ = prewitt(img)
        self.assertGreater(max(mag.planes[0]), 0)

    def test_scharr_detects_edges(self):
        img = make_shapes(32, 32)
        _, _, mag, _ = scharr(img)
        self.assertGreater(max(mag.planes[0]), 0)

    def test_canny_all_four_edges_of_square(self):
        """Canny must find edges on all 4 sides of a filled white square."""
        img = Image(64, 64, 'L', fill=0.0)
        for r in range(15, 50):
            for c in range(15, 50):
                img.planes[0][r * 64 + c] = 1.0
        edges = canny(img, sigma=1.0, low=0.05, high=0.15)
        ep = edges.planes[0]
        top = sum(1 for c in range(15, 50) if ep[15 * 64 + c] > 0.5)
        bot = sum(1 for c in range(15, 50) if ep[49 * 64 + c] > 0.5)
        left = sum(1 for r in range(15, 50) if ep[r * 64 + 15] > 0.5)
        right = sum(1 for r in range(15, 50) if ep[r * 64 + 49] > 0.5)
        self.assertGreater(top, 5)
        self.assertGreater(bot, 5)
        self.assertGreater(left, 5)
        self.assertGreater(right, 5)

    def test_canny_returns_L_mode(self):
        img = make_shapes(32, 32)
        self.assertEqual(canny(img).mode, 'L')

    def test_canny_values_binary(self):
        """Canny output must be exactly 0 or 1 (no intermediate values)."""
        img = make_shapes(64, 64)
        edges = canny(img)
        vals = set(round(v, 6) for v in edges.planes[0])
        self.assertLessEqual(vals, {0.0, 1.0})

    def test_canny_on_flat_image(self):
        img = Image(32, 32, 'L', fill=0.5)
        edges = canny(img)
        self.assertEqual(max(edges.planes[0]), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Feature detection
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureDetection(unittest.TestCase):

    def test_harris_checkerboard_at_intersections(self):
        """Harris corners on a checkerboard must fall on grid intersections."""
        checker = make_checkerboard(64, 64, cell=8)
        corners = harris_corners(checker, top_n=20)
        self.assertGreater(len(corners), 0)
        for r, c, s in corners:
            # Within 2 pixels of a grid intersection
            self.assertLessEqual(min(r % 8, 8 - r % 8), 2,
                                 msg=f"Corner at row {r} not near grid")
            self.assertLessEqual(min(c % 8, 8 - c % 8), 2,
                                 msg=f"Corner at col {c} not near grid")

    def test_harris_on_flat_image(self):
        img = Image(32, 32, 'L', fill=0.5)
        corners = harris_corners(img)
        self.assertEqual(corners, [])

    def test_harris_scores_descending(self):
        checker = make_checkerboard(64, 64, cell=8)
        corners = harris_corners(checker, top_n=30)
        scores = [s for _, _, s in corners]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_harris_nms_spacing(self):
        """No two Harris corners should be within nms_radius of each other."""
        checker = make_checkerboard(64, 64, cell=8)
        nms_r = 5
        corners = harris_corners(checker, nms_radius=nms_r, top_n=30)
        for i in range(len(corners)):
            for j in range(i + 1, len(corners)):
                r1, c1, _ = corners[i]
                r2, c2, _ = corners[j]
                dist = max(abs(r1 - r2), abs(c1 - c2))
                self.assertGreater(dist, 0, msg=f"Duplicate corner at ({r1},{c1})")

    def test_fast_detects_corners_of_square(self):
        """FAST should detect corners at the 4 corners of a white square."""
        img = Image(64, 64, 'L', fill=0.0)
        for r in range(20, 45):
            for c in range(20, 45):
                img.planes[0][r * 64 + c] = 1.0
        corners = fast_corners(img, threshold=0.10, top_n=20)
        self.assertGreater(len(corners), 0)

    def test_fast_on_flat_image(self):
        img = Image(32, 32, 'L', fill=0.5)
        corners = fast_corners(img, threshold=0.1)
        self.assertEqual(corners, [])

    def test_fast_scores_descending(self):
        shapes = make_shapes(64, 64)
        corners = fast_corners(shapes, top_n=30)
        scores = [s for _, _, s in corners]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ─────────────────────────────────────────────────────────────────────────────
# Morphological operations
# ─────────────────────────────────────────────────────────────────────────────

class TestMorphology(unittest.TestCase):

    def _binary(self, img):
        _, b = threshold_otsu(img)
        return b

    def test_dilate_empty(self):
        empty = Image(32, 32, 'L', fill=0.0)
        se = make_se('cross', 3)
        d = dilate(empty, se)
        self.assertEqual(max(d.planes[0]), 0.0)

    def test_erode_full_interior(self):
        """Interior pixels of a full image survive erosion (zero-padding erodes border)."""
        full = Image(16, 16, 'L', fill=1.0)
        se = make_se('cross', 3)  # radius=1
        e = erode(full, se)
        # Interior 14×14 should all be 1
        for r in range(1, 15):
            for c in range(1, 15):
                self.assertEqual(e.planes[0][r * 16 + c], 1.0)

    def test_erosion_subset_of_original(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('disk', 5)
        e = erode(img, se)
        for v_e, v_i in zip(e.planes[0], img.planes[0]):
            self.assertLessEqual(v_e, v_i + 1e-9)

    def test_dilation_superset_of_original(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('square', 5)
        d = dilate(img, se)
        for v_d, v_i in zip(d.planes[0], img.planes[0]):
            self.assertGreaterEqual(v_d, v_i - 1e-9)

    def test_opening_subset_of_original(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('cross', 3)
        o = opening(img, se)
        for v_o, v_i in zip(o.planes[0], img.planes[0]):
            self.assertLessEqual(v_o, v_i + 1e-9)

    def test_closing_superset_of_original(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('cross', 3)
        c = closing(img, se)
        for v_c, v_i in zip(c.planes[0], img.planes[0]):
            self.assertGreaterEqual(v_c, v_i - 1e-9)

    def test_make_se_shapes(self):
        cross = make_se('cross', 3)
        self.assertIn((0, 0), cross)
        self.assertIn((1, 0), cross)
        self.assertIn((0, 1), cross)
        sq = make_se('square', 3)
        self.assertEqual(len(sq), 9)
        disk = make_se('disk', 5)
        self.assertIn((0, 0), disk)

    def test_top_hat_nonnegative(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('disk', 5)
        th = top_hat(img, se)
        self.assertGreaterEqual(min(th.planes[0]), 0.0)

    def test_black_hat_nonnegative(self):
        img = self._binary(make_shapes(64, 64))
        se = make_se('disk', 5)
        bh = black_hat(img, se)
        self.assertGreaterEqual(min(bh.planes[0]), 0.0)

    def test_morph_gradient_nonnegative(self):
        img = self._binary(make_shapes(32, 32))
        se = make_se('cross', 3)
        g = morph_gradient(img, se)
        self.assertGreaterEqual(min(g.planes[0]), 0.0)

    def test_hit_or_miss(self):
        img = Image(8, 8, 'L', fill=0.0)
        img.planes[0][4 * 8 + 4] = 1.0   # single isolated pixel
        se_hit = [(0, 0)]                  # must be set at center
        se_miss = [(0, 1), (0, -1), (1, 0), (-1, 0)]  # must be unset around
        result = hit_or_miss(img, se_hit, se_miss)
        # The isolated pixel satisfies both conditions
        self.assertGreater(result.planes[0][4 * 8 + 4], 0.5)

    def test_invalid_se_shape(self):
        with self.assertRaises(ValueError):
            make_se('hexagon', 5)


# ─────────────────────────────────────────────────────────────────────────────
# Connected components
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectedComponents(unittest.TestCase):

    def _two_blobs(self):
        img = Image(32, 32, 'L', fill=0.0)
        for r in range(5, 12):
            for c in range(5, 12): img.planes[0][r * 32 + c] = 1.0
        for r in range(20, 27):
            for c in range(20, 27): img.planes[0][r * 32 + c] = 1.0
        return img

    def test_two_isolated_blobs(self):
        _, n, _, _ = connected_components(self._two_blobs())
        self.assertEqual(n, 2)

    def test_shapes_three_components(self):
        img = make_shapes(64, 64)
        _, binary = threshold_otsu(img)
        _, n, info, _ = connected_components(binary)
        self.assertEqual(n, 3)

    def test_empty_image_zero_components(self):
        img = Image(16, 16, 'L', fill=0.0)
        _, n, info, _ = connected_components(img)
        self.assertEqual(n, 0)
        self.assertEqual(info, {})

    def test_full_image_one_component(self):
        img = Image(16, 16, 'L', fill=1.0)
        _, n, info, _ = connected_components(img)
        self.assertEqual(n, 1)
        self.assertEqual(info[1]['size'], 16 * 16)

    def test_component_size_correct(self):
        img = Image(32, 32, 'L', fill=0.0)
        # 5×5 blob
        for r in range(10, 15):
            for c in range(10, 15): img.planes[0][r * 32 + c] = 1.0
        _, n, info, _ = connected_components(img)
        self.assertEqual(n, 1)
        self.assertEqual(info[1]['size'], 25)

    def test_component_bbox(self):
        img = Image(32, 32, 'L', fill=0.0)
        for r in range(8, 13):
            for c in range(4, 9): img.planes[0][r * 32 + c] = 1.0
        _, n, info, _ = connected_components(img)
        self.assertEqual(n, 1)
        x, y, w, h = info[1]['bbox']
        self.assertEqual(x, 4); self.assertEqual(y, 8)
        self.assertEqual(w, 5); self.assertEqual(h, 5)

    def test_connectivity_4_vs_8(self):
        # Diagonal pixels: 4-connectivity sees 2 components, 8-connectivity sees 1
        img = Image(4, 4, 'L', fill=0.0)
        img.planes[0][0 * 4 + 0] = 1.0  # top-left
        img.planes[0][1 * 4 + 1] = 1.0  # diagonal
        _, n4, _, _ = connected_components(img, connectivity=4)
        _, n8, _, _ = connected_components(img, connectivity=8)
        self.assertEqual(n4, 2)
        self.assertEqual(n8, 1)

    def test_colorize_labels_produces_rgb(self):
        labels = [0, 1, 2, 1, 0, 2, 0, 0, 0]
        c = colorize_labels(labels, 2, 3, 3)
        self.assertEqual(c.mode, 'RGB')


# ─────────────────────────────────────────────────────────────────────────────
# Thresholding
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholding(unittest.TestCase):

    def test_otsu_binary_image(self):
        """Otsu on a binary image correctly separates the two values."""
        img = Image(32, 32, 'L')
        img.planes[0] = [0.0] * 512 + [1.0] * 512
        t, binary = threshold_otsu(img)
        self.assertGreater(t, 0.0)
        self.assertLess(t, 1.0)
        n_ones = sum(1 for v in binary.planes[0] if v > 0.5)
        self.assertEqual(n_ones, 512)

    def test_otsu_flat_image(self):
        """Flat image: Otsu should return a threshold, all pixels same class."""
        img = Image(16, 16, 'L', fill=0.5)
        t, binary = threshold_otsu(img)
        # All pixels either 0 or 1 (one class)
        vals = set(round(v) for v in binary.planes[0])
        self.assertEqual(len(vals), 1)

    def test_adaptive_produces_binary(self):
        img = make_shapes(32, 32)
        result = threshold_adaptive(img, block_size=9, C=0.02)
        vals = set(round(v, 6) for v in result.planes[0])
        self.assertLessEqual(vals, {0.0, 1.0})

    def test_threshold_output_mode(self):
        img = Image(10, 10, 'L', fill=0.5)
        _, binary = threshold_otsu(img)
        self.assertEqual(binary.mode, 'L')


# ─────────────────────────────────────────────────────────────────────────────
# Hough transform
# ─────────────────────────────────────────────────────────────────────────────

class TestHough(unittest.TestCase):

    def test_horizontal_line_theta_90(self):
        """A horizontal line in an edge image → Hough peak at θ≈90°."""
        img = Image(64, 32, 'L', fill=0.0)
        for c in range(64): img.planes[0][16 * 64 + c] = 1.0
        lines = hough_lines(img, threshold=0.5, top_n=3)
        self.assertGreater(len(lines), 0)
        theta = lines[0][1]
        self.assertAlmostEqual(theta, 90.0, delta=5.0)

    def test_vertical_line_theta_0(self):
        """A vertical line → Hough peak at θ≈0°."""
        img = Image(32, 64, 'L', fill=0.0)
        for r in range(64): img.planes[0][r * 32 + 16] = 1.0
        lines = hough_lines(img, threshold=0.5, top_n=3)
        self.assertGreater(len(lines), 0)
        # theta near 0 or 180
        theta = lines[0][1]
        self.assertTrue(theta < 10 or theta > 170, msg=f"theta={theta}")

    def test_empty_image_no_lines(self):
        img = Image(32, 32, 'L', fill=0.0)
        lines = hough_lines(img, threshold=0.5)
        self.assertEqual(lines, [])

    def test_lines_sorted_by_score(self):
        shapes = make_shapes(64, 64)
        edges = canny(shapes.grayscale() if shapes.mode != 'L' else shapes)
        lines = hough_lines(edges, top_n=10)
        scores = [s for _, _, s in lines]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_draw_lines_returns_rgb(self):
        img = make_shapes(64, 64)
        out = draw_lines(img, [(0.0, 90.0, 1.0)])
        self.assertEqual(out.mode, 'RGB')


# ─────────────────────────────────────────────────────────────────────────────
# Template matching
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateMatch(unittest.TestCase):

    def test_exact_match_ncc_1(self):
        """A template placed exactly in an image → NCC = 1.0 at that position."""
        img = Image(64, 64, 'L', fill=0.1)
        tmpl_src = make_shapes(20, 20)
        # Place at (10, 12)
        for r in range(20):
            for c in range(20):
                img.planes[0][(10 + r) * 64 + (12 + c)] = tmpl_src.planes[0][r * 20 + c]
        corr = template_match_ncc(img, tmpl_src)
        self.assertAlmostEqual(max(corr.planes[0]), 1.0, delta=0.01)

    def test_find_matches_returns_expected_count(self):
        circles_img, centers = make_circles(100, 100, n=3, radius=10)
        gray = circles_img.grayscale()
        if centers:
            cx, cy = centers[0]
            tmpl = gray.crop(cx - 11, cy - 11, 22, 22)
            corr = template_match_ncc(gray, tmpl)
            matches = find_matches(corr, 22, 22, threshold=0.80)
            self.assertGreaterEqual(len(matches), 1)

    def test_template_larger_than_image_raises(self):
        img = Image(30, 30, 'L')
        tmpl = Image(40, 40, 'L')
        with self.assertRaises(ValueError):
            template_match_ncc(img, tmpl)

    def test_flat_template_returns_empty(self):
        """Flat (zero-variance) template → NCC undefined → all-zero response."""
        img = make_shapes(32, 32).grayscale()
        tmpl = Image(8, 8, 'L', fill=0.5)
        corr = template_match_ncc(img, tmpl)
        self.assertAlmostEqual(max(corr.planes[0]), 0.0, delta=1e-6)

    def test_ncc_response_in_range(self):
        img = make_shapes(32, 32)
        tmpl = img.crop(5, 5, 10, 10)
        corr = template_match_ncc(img, tmpl)
        self.assertGreaterEqual(min(corr.planes[0]), 0.0)
        self.assertLessEqual(max(corr.planes[0]), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Bilateral filter
# ─────────────────────────────────────────────────────────────────────────────

class TestBilateralFilter(unittest.TestCase):

    def test_flat_image_unchanged(self):
        """Bilateral filter on a flat image must return the same flat image."""
        img = Image(16, 16, 'L', fill=0.6)
        out = bilateral_filter(img, sigma_s=1.5, sigma_r=0.1)
        self.assertAlmostEqual(max(out.planes[0]), 0.6, delta=1e-6)
        self.assertAlmostEqual(min(out.planes[0]), 0.6, delta=1e-6)

    def test_edge_preserved(self):
        """
        Bilateral filter must preserve a sharp step edge better than Gaussian.
        At an edge pixel, bilateral should have a closer value to the original
        than Gaussian blur (which blurs across the edge).
        """
        img = Image(32, 32, 'L')
        for r in range(32):
            for c in range(32):
                img.planes[0][r * 32 + c] = 1.0 if c >= 16 else 0.0

        gauss = gaussian_blur(img, sigma=2.0)
        bilat = bilateral_filter(img, sigma_s=2.0, sigma_r=0.1)

        # At column 16, the true value is 1.0 (just inside white region)
        # Bilateral should be closer to 1.0 than Gaussian
        bilat_val = bilat.planes[0][16 * 32 + 16]
        gauss_val = gauss.planes[0][16 * 32 + 16]
        self.assertGreater(bilat_val, gauss_val,
                           msg="Bilateral should be closer to original at edge")

    def test_rgb_mode(self):
        img = Image(16, 16, 'RGB', fill=0.5)
        out = bilateral_filter(img, sigma_s=1.0, sigma_r=0.1)
        self.assertEqual(out.mode, 'RGB')

    def test_output_in_range(self):
        import random; rng = random.Random(7)
        img = Image(20, 20, 'L')
        img.planes[0] = [rng.random() for _ in range(400)]
        out = bilateral_filter(img, sigma_s=1.5, sigma_r=0.2)
        self.assertGreaterEqual(min(out.planes[0]), 0.0)
        self.assertLessEqual(max(out.planes[0]), 1.0)

    def test_denoising_reduces_variance(self):
        """Bilateral filter on a noisy version of a flat region should reduce variance."""
        import random; rng = random.Random(42)
        img = Image(32, 32, 'L')
        img.planes[0] = [0.5 + rng.gauss(0, 0.1) for _ in range(32 * 32)]
        out = bilateral_filter(img, sigma_s=2.5, sigma_r=0.15)
        import statistics
        var_in  = statistics.variance(img.planes[0])
        var_out = statistics.variance(out.planes[0])
        self.assertLess(var_out, var_in)


# ─────────────────────────────────────────────────────────────────────────────
# HTML visualizer
# ─────────────────────────────────────────────────────────────────────────────

class TestHTMLViz(unittest.TestCase):

    def test_build_pipeline_html_valid(self):
        stages = [('A', Image(8, 8, 'L', fill=0.5)), ('B', Image(8, 8, 'RGB', fill=0.3))]
        html = build_pipeline_html(stages)
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('data:image/png;base64,', html)
        self.assertIn('"name":', html)
        self.assertIn('"A"', html)
        self.assertIn('"B"', html)

    def test_build_pipeline_html_empty(self):
        html = build_pipeline_html([])
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('STAGES=[]', html)

    def test_html_contains_title(self):
        html = build_pipeline_html([('Test Stage', Image(4, 4, 'L'))])
        self.assertIn('Optic', html)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic image generation
# ─────────────────────────────────────────────────────────────────────────────

class TestSyntheticImages(unittest.TestCase):

    def test_checkerboard_values_binary(self):
        img = make_checkerboard(32, 32, cell=8)
        vals = set(img.planes[0])
        self.assertLessEqual(vals, {0.0, 1.0})

    def test_checkerboard_mode(self):
        img = make_checkerboard(32, 32)
        self.assertEqual(img.mode, 'L')

    def test_shapes_has_3_components(self):
        img = make_shapes(64, 64)
        _, binary = threshold_otsu(img)
        _, n, _, _ = connected_components(binary)
        self.assertEqual(n, 3)

    def test_shapes_foreground_count(self):
        img = make_shapes(128, 128)
        n_fg = sum(1 for v in img.planes[0] if v > 0.5)
        # Should have a reasonable number of foreground pixels
        self.assertGreater(n_fg, 100)
        self.assertLess(n_fg, 128 * 128)

    def test_circles_returns_tuple(self):
        result = make_circles(64, 64, n=3, radius=8)
        self.assertIsInstance(result, tuple)
        img, centers = result
        self.assertEqual(img.mode, 'RGB')
        self.assertLessEqual(len(centers), 3)

    def test_lines_image_has_correct_mode(self):
        img = make_lines_image(32, 32)
        self.assertEqual(img.mode, 'L')


if __name__ == '__main__':
    unittest.main()
