import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import colorspace


class TestColorspace(unittest.TestCase):
    def test_rgb_ycbcr_round_trip(self):
        for r, g, b in [(0, 0, 0), (255, 255, 255), (128, 64, 200), (17, 233, 9), (255, 0, 0), (0, 255, 0), (0, 0, 255)]:
            y, cb, cr = colorspace.rgb_to_ycbcr(r, g, b)
            r2, g2, b2 = colorspace.ycbcr_to_rgb(y, cb, cr)
            self.assertAlmostEqual(r, r2, delta=0.01)
            self.assertAlmostEqual(g, g2, delta=0.01)
            self.assertAlmostEqual(b, b2, delta=0.01)

    def test_gray_has_zero_chroma(self):
        # For R=G=B, Cb and Cr should both land exactly on 128 (no color).
        y, cb, cr = colorspace.rgb_to_ycbcr(100, 100, 100)
        self.assertAlmostEqual(cb, 128.0, places=6)
        self.assertAlmostEqual(cr, 128.0, places=6)
        self.assertAlmostEqual(y, 100.0, places=6)

    def test_subsample_averages(self):
        # A 2x2 block of [0, 100, 200, 300] averages to 150.
        plane = [0.0, 100.0, 200.0, 300.0]
        out, ow, oh = colorspace.subsample_plane(plane, 2, 2, 2, 2)
        self.assertEqual((ow, oh), (1, 1))
        self.assertAlmostEqual(out[0], 150.0)

    def test_subsample_output_shape(self):
        plane = [0.0] * (17 * 9)
        out, ow, oh = colorspace.subsample_plane(plane, 17, 9, 2, 2)
        self.assertEqual(ow, 9)  # ceil(17/2)
        self.assertEqual(oh, 5)  # ceil(9/2)

    def test_upsample_is_smooth_bilinear_interpolation(self):
        # Bilinear upsampling should monotonically interpolate between
        # subsampled values, not block-replicate them -- the interior
        # samples must land strictly between the two source values.
        sub = [10.0, 20.0]
        out = colorspace.upsample_plane(sub, 2, 1, 2, 1, 4, 1)
        self.assertEqual(len(out), 4)
        for v in out:
            self.assertTrue(10.0 <= v <= 20.0)
        # monotonically non-decreasing across a monotonic source
        for a, b in zip(out, out[1:]):
            self.assertLessEqual(a, b)
        # values nearer sample 1 should be closer to 20 than values nearer sample 0
        self.assertLess(out[0], out[-1])

    def test_upsample_constant_plane_stays_constant(self):
        sub = [42.0] * 6  # 3x2
        out = colorspace.upsample_plane(sub, 3, 2, 2, 2, 6, 4)
        self.assertTrue(all(abs(v - 42.0) < 1e-9 for v in out))

    def test_upsample_no_subsampling_is_identity(self):
        plane = [1.0, 2.0, 3.0, 4.0]
        out = colorspace.upsample_plane(plane, 2, 2, 1, 1, 2, 2)
        self.assertEqual(out, plane)

    def test_pad_crop_round_trip(self):
        plane = [1.0, 2.0, 3.0, 4.0]  # 2x2
        padded = colorspace.pad_plane(plane, 2, 2, 4, 4)
        self.assertEqual(len(padded), 16)
        cropped = colorspace.crop_plane(padded, 4, 2, 2)
        self.assertEqual(cropped, plane)

    def test_pad_replicates_edges(self):
        plane = [5.0, 9.0]
        padded = colorspace.pad_plane(plane, 2, 1, 4, 3)
        # every row should replicate the last column (9.0) into the pad
        for y in range(3):
            self.assertEqual(padded[y * 4 + 2], 9.0)
            self.assertEqual(padded[y * 4 + 3], 9.0)

    def test_image_ycbcr_round_trip_near_identity(self):
        r = [10, 250, 128, 0]
        g = [200, 5, 128, 255]
        b = [30, 80, 128, 128]
        img = colorspace.Image(2, 2, r, g, b)
        y, cb, cr = img.to_ycbcr_planes()
        img2 = colorspace.Image.from_ycbcr_planes(2, 2, y, cb, cr)
        for a, bb in zip(img.r, img2.r):
            self.assertLessEqual(abs(a - bb), 1)
        for a, bb in zip(img.g, img2.g):
            self.assertLessEqual(abs(a - bb), 1)
        for a, bb in zip(img.b, img2.b):
            self.assertLessEqual(abs(a - bb), 1)


if __name__ == "__main__":
    unittest.main()
