import shutil
import subprocess
import tempfile
import unittest

from vignette import decoder, encoder, metrics, tables
from vignette.image import TEST_IMAGES, Image, gradient, circles


class TestMarkers(unittest.TestCase):
    def test_starts_with_soi_ends_with_eoi(self):
        data, _ = encoder.encode(gradient(32, 32), quality=70)
        self.assertEqual(data[:2], bytes([0xFF, 0xD8]))
        self.assertEqual(data[-2:], bytes([0xFF, 0xD9]))

    def test_recognized_as_real_jpeg_by_file_utility(self):
        # Independent external oracle: the standard `file` utility parses
        # real JPEG marker structure. Skips cleanly if unavailable.
        if shutil.which("file") is None:
            self.skipTest("`file` utility not available in this environment")
        data, _ = encoder.encode(gradient(48, 33), quality=80)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(data)
            f.flush()
            out = subprocess.run(
                ["file", "-b", f.name], capture_output=True, text=True, check=True
            ).stdout
        self.assertIn("JPEG", out)
        self.assertIn("baseline", out)
        self.assertIn("48x33", out)


class TestQuantTableIndexingRegression(unittest.TestCase):
    """Guards against the natural-order/zigzag-order indexing bug found
    during adversarial review (REVIEW.md #1): it was invisible at quality
    100 (every quant divisor scales to 1) but corrupted images at any
    quality where table entries differ, because the quantize step, the
    DQT marker writer, and the decoder's dequantize step each indexed the
    natural-order-stored quant table by the wrong (zigzag) position."""

    def test_psnr_stays_high_away_from_quality_100(self):
        img = gradient(64, 64)
        for q in (95, 85, 75, 60):
            data, _ = encoder.encode(img, quality=q)
            recon = decoder.decode(data)
            psnr = metrics.psnr(img, recon)
            self.assertGreater(
                psnr, 30, f"quality={q} gave suspiciously low PSNR {psnr:.2f} dB"
            )

    def test_quant_table_written_in_zigzag_order_in_file(self):
        # DQT payload byte i must equal the natural-order table at
        # position ZIGZAG[i] (the spec's zigzag storage order).
        qt = tables.scale_quant_table(tables.STD_LUMINANCE_QT, 77)
        seg = encoder._marker_dqt(0, qt)
        body = seg[4:]  # skip FF DB + 2-byte length
        payload = body[1:]  # skip precision/id byte
        for i in range(64):
            self.assertEqual(payload[i], qt[tables.ZIGZAG[i]])


class TestRoundTrip(unittest.TestCase):
    def test_all_test_images_all_qualities(self):
        for name, gen in TEST_IMAGES.items():
            img = gen(64, 64)
            for q in (95, 75, 50, 25, 10):
                with self.subTest(image=name, quality=q):
                    data, _ = encoder.encode(img, quality=q)
                    recon = decoder.decode(data)
                    self.assertEqual(recon.width, img.width)
                    self.assertEqual(recon.height, img.height)
                    psnr = metrics.psnr(img, recon)
                    # Even at quality 10 a real photo-like image should
                    # not fall apart completely.
                    self.assertGreater(psnr, 15)

    def test_psnr_is_monotonic_in_quality(self):
        img = circles(64, 64)
        qualities = [10, 30, 50, 70, 90]
        psnrs = []
        for q in qualities:
            data, _ = encoder.encode(img, quality=q)
            recon = decoder.decode(data)
            psnrs.append(metrics.psnr(img, recon))
        for a, b in zip(psnrs, psnrs[1:]):
            self.assertLessEqual(a, b + 1e-9)

    def test_non_multiple_of_16_dimensions(self):
        for w, h in [(1, 1), (7, 7), (15, 17), (100, 73), (33, 200)]:
            img = gradient(w, h)
            data, _ = encoder.encode(img, quality=70)
            recon = decoder.decode(data)
            self.assertEqual((recon.width, recon.height), (w, h))

    def test_quality_extremes_and_out_of_range_clamp(self):
        img = gradient(48, 48)
        for q in (-10, 0, 1, 100, 150):
            data, _ = encoder.encode(img, quality=q)
            recon = decoder.decode(data)
            self.assertEqual((recon.width, recon.height), (48, 48))

    def test_flat_color_images_compress_well(self):
        img = Image(32, 32, [(120, 140, 160)] * 1024)
        data, _ = encoder.encode(img, quality=70)
        recon = decoder.decode(data)
        self.assertLess(len(data), 32 * 32 * 3 // 4)
        self.assertGreater(metrics.psnr(img, recon), 35)

    def test_all_63_ac_coefficients_nonzero_block(self):
        zz = [5] + list(range(1, 64))
        syms, _ = encoder._block_symbols(zz, 0, "DC", "AC")
        has_eob = any(cls == "AC" and sym == 0x00 for cls, sym, _, _ in syms)
        self.assertFalse(has_eob)


class TestOptimalHuffman(unittest.TestCase):
    def test_lossless_relative_to_standard_tables_but_smaller(self):
        img = circles(64, 64)
        std_data, std_stats = encoder.encode(img, quality=60, optimal_huffman=False)
        opt_data, opt_stats = encoder.encode(img, quality=60, optimal_huffman=True)
        std_recon = decoder.decode(std_data)
        opt_recon = decoder.decode(opt_data)
        self.assertEqual(std_recon.pixels, opt_recon.pixels)
        self.assertLess(len(opt_data), len(std_data))
        self.assertTrue(any(opt_stats["used_optimal_huffman"].values()))


class TestMalformedInput(unittest.TestCase):
    def test_raises_clear_errors_not_crashes(self):
        cases = [b"", b"not a jpeg", bytes([0xFF, 0xD8])]
        for data in cases:
            with self.assertRaises(decoder.JpegSyntaxError):
                decoder.decode(data)

    def test_truncated_entropy_data_raises(self):
        data, _ = encoder.encode(gradient(32, 32), quality=70)
        sos = data.find(bytes([0xFF, 0xDA]))
        seg_len = (data[sos + 2] << 8) | data[sos + 3]
        entropy_start = sos + 2 + seg_len
        truncated = data[: entropy_start + 3]
        with self.assertRaises(EOFError):
            decoder.decode(truncated)


if __name__ == "__main__":
    unittest.main()
