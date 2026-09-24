import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import decoder, encoder, metrics, progressive, testimages
from spectral.decoder import JpegDecodeError
from spectral.markers import JpegParseError


class TestProgressive(unittest.TestCase):
    def test_is_progressive_detection(self):
        img = testimages.gradient(32, 32)
        baseline = encoder.encode(img, quality=70)
        prog = progressive.encode(img, quality=70)
        self.assertFalse(progressive.is_progressive(baseline))
        self.assertTrue(progressive.is_progressive(prog))

    def test_sof2_marker_used(self):
        img = testimages.gradient(16, 16)
        data = progressive.encode(img, quality=70)
        self.assertIn(bytes([0xFF, 0xC2]), data)  # SOF2
        self.assertNotIn(bytes([0xFF, 0xC0]), data)  # not SOF0

    def test_multiple_scans_present(self):
        # 2 DC scans + 2 AC bands x 3 components = 8 scans.
        img = testimages.gradient(32, 32)
        data = progressive.encode(img, quality=70)
        self.assertEqual(data.count(bytes([0xFF, 0xDA])), 8)  # SOS markers

    def test_round_trip_all_subsampling_modes(self):
        img = testimages.synthetic_photo(48, 48, seed=4)
        for ss in ("444", "422", "420"):
            data = progressive.encode(img, quality=75, subsampling=ss)
            out = progressive.decode(data)
            self.assertEqual((out.width, out.height), (48, 48))
            self.assertGreater(metrics.psnr(img, out), 20.0)

    def test_odd_dimensions_round_trip(self):
        for w, h in [(1, 1), (9, 5), (65, 50)]:
            img = testimages.gradient(w, h)
            data = progressive.encode(img, quality=80)
            out = progressive.decode(data)
            self.assertEqual((out.width, out.height), (w, h))

    def test_solid_color_is_lossless_like_baseline(self):
        img = testimages.solid(16, 16, (30, 200, 90))
        data = progressive.encode(img, quality=90, subsampling="444")
        out = progressive.decode(data)
        self.assertEqual(metrics.psnr(img, out), float("inf"))

    def test_progressive_psnr_close_to_baseline_at_same_quality(self):
        # Both encoders share the exact same forward DCT/quantization
        # pipeline (encoder.forward_transform), so splitting the same
        # coefficients across more scans should barely change fidelity.
        img = testimages.synthetic_photo(64, 64, seed=8)
        base_data = encoder.encode(img, quality=70, subsampling="420")
        prog_data = progressive.encode(img, quality=70, subsampling="420")
        base_psnr = metrics.psnr(img, decoder.decode(base_data))
        prog_psnr = metrics.psnr(img, progressive.decode(prog_data))
        self.assertAlmostEqual(base_psnr, prog_psnr, delta=0.5)

    def test_decode_rejects_baseline_file(self):
        img = testimages.gradient(16, 16)
        data = encoder.encode(img, quality=70)
        with self.assertRaises(JpegDecodeError):
            progressive.decode(data)

    def test_baseline_decoder_rejects_progressive_file(self):
        img = testimages.gradient(16, 16)
        data = progressive.encode(img, quality=70)
        with self.assertRaises(JpegDecodeError):
            decoder.decode(data)

    def test_decode_rejects_garbage_cleanly(self):
        with self.assertRaises((JpegParseError, JpegDecodeError)):
            progressive.decode(b"not a jpeg at all")

    def test_is_progressive_false_on_garbage(self):
        self.assertFalse(progressive.is_progressive(b"not a jpeg"))

    def test_ac_band_tokens_round_trip_via_full_pipeline(self):
        # A high-frequency-heavy image forces many nonzero AC
        # coefficients across both spectral bands (1-5 and 6-63),
        # exercising the ZRL/EOB-run logic in _ac_band_tokens more than
        # a smooth image would.
        img = testimages.checkerboard(64, 64, cell=1)
        data = progressive.encode(img, quality=85, subsampling="444")
        out = progressive.decode(data)
        self.assertGreater(metrics.psnr(img, out), 15.0)

    def test_bit_flip_fuzz_never_raises_an_unhandled_exception(self):
        import random
        rng = random.Random(20260924)
        img = testimages.synthetic_photo(40, 32, seed=1)
        data = progressive.encode(img, quality=60, subsampling="420")
        for _ in range(150):
            corrupted = bytearray(data)
            idx = rng.randrange(len(corrupted))
            corrupted[idx] ^= 1 << rng.randrange(8)
            try:
                progressive.decode(bytes(corrupted))
            except (JpegParseError, JpegDecodeError):
                pass
            except Exception as e:  # pragma: no cover - failure case
                self.fail(f"byte {idx} raised unhandled {type(e).__name__}: {e}")


if __name__ == "__main__":
    unittest.main()
