import os
import tempfile
import unittest

from vignette.image import Image, gradient, checkerboard, circles, plasma, text_bars


class TestImage(unittest.TestCase):
    def test_rejects_nonpositive_dims(self):
        for w, h in [(0, 5), (5, 0), (-1, 5), (5, -1)]:
            with self.assertRaises(ValueError):
                Image(w, h)

    def test_get_clamps_out_of_bounds(self):
        img = Image(4, 4, [(i, i, i) for i in range(16)])
        self.assertEqual(img.get(-5, -5), img.get(0, 0))
        self.assertEqual(img.get(100, 100), img.get(3, 3))

    def test_crop_matches_source_pixels(self):
        img = gradient(20, 20)
        crop = img.crop(5, 5, 4, 4)
        self.assertEqual(crop.width, 4)
        self.assertEqual(crop.height, 4)
        for y in range(4):
            for x in range(4):
                self.assertEqual(crop.get(x, y), img.get(5 + x, 5 + y))

    def test_ppm_round_trip(self):
        img = gradient(17, 9)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.ppm")
            img.save_ppm(path)
            back = Image.load_ppm(path)
        self.assertEqual(back.width, img.width)
        self.assertEqual(back.height, img.height)
        self.assertEqual(back.pixels, img.pixels)

    def test_ppm_with_comment_header(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.ppm")
            with open(path, "wb") as f:
                f.write(b"P6\n# a comment\n4 3\n255\n")
                f.write(bytes([10, 20, 30] * 12))
            img = Image.load_ppm(path)
        self.assertEqual((img.width, img.height), (4, 3))
        self.assertEqual(img.get(0, 0), (10, 20, 30))

    def test_ppm_rejects_wrong_magic(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.ppm")
            with open(path, "wb") as f:
                f.write(b"not a ppm file")
            with self.assertRaises(ValueError):
                Image.load_ppm(path)

    def test_procedural_generators_produce_correct_size(self):
        for gen in (gradient, checkerboard, circles, plasma, text_bars):
            img = gen(30, 20)
            self.assertEqual(img.width, 30)
            self.assertEqual(img.height, 20)
            self.assertEqual(len(img.pixels), 600)
            for (r, g, b) in img.pixels[:50]:
                for c in (r, g, b):
                    self.assertTrue(0 <= c <= 255)

    def test_plasma_is_deterministic(self):
        a = plasma(16, 16, seed=7)
        b = plasma(16, 16, seed=7)
        self.assertEqual(a.pixels, b.pixels)
        c = plasma(16, 16, seed=8)
        self.assertNotEqual(a.pixels, c.pixels)


if __name__ == "__main__":
    unittest.main()
