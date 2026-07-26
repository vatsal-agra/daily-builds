import unittest

from vignette import metrics
from vignette.image import Image, gradient


class TestMetrics(unittest.TestCase):
    def test_psnr_identical_images_is_infinite(self):
        img = gradient(16, 16)
        self.assertEqual(metrics.psnr(img, img.copy()), float("inf"))

    def test_ssim_identical_images_is_one(self):
        img = gradient(16, 16)
        self.assertAlmostEqual(metrics.ssim(img, img.copy()), 1.0, places=9)

    def test_psnr_decreases_with_more_noise(self):
        base = Image(16, 16, [(100, 100, 100)] * 256)
        small_noise = base.copy()
        small_noise.set(0, 0, (105, 100, 100))
        big_noise = base.copy()
        big_noise.set(0, 0, (255, 0, 0))
        self.assertGreater(metrics.psnr(base, small_noise), metrics.psnr(base, big_noise))

    def test_mismatched_dims_raise(self):
        a = gradient(10, 10)
        b = gradient(12, 10)
        with self.assertRaises(ValueError):
            metrics.psnr(a, b)
        with self.assertRaises(ValueError):
            metrics.ssim(a, b)

    def test_compression_stats_sane(self):
        img = gradient(16, 16)
        stats = metrics.compression_stats(img, b"x" * 100)
        self.assertEqual(stats["raw_bytes"], 16 * 16 * 3)
        self.assertEqual(stats["compressed_bytes"], 100)
        self.assertAlmostEqual(stats["ratio"], (16 * 16 * 3) / 100)


if __name__ == "__main__":
    unittest.main()
