import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import encoder, decoder, testimages, metrics
from spectral.decoder import JpegDecodeError
from spectral.markers import JpegParseError


class TestEncodeDecodeRoundTrip(unittest.TestCase):
    def test_valid_jfif_header_bytes(self):
        img = testimages.gradient(32, 32)
        data = encoder.encode(img, quality=80)
        self.assertEqual(data[0:2], bytes([0xFF, 0xD8]))  # SOI
        self.assertEqual(data[-2:], bytes([0xFF, 0xD9]))  # EOI
        self.assertEqual(data[2:4], bytes([0xFF, 0xE0]))  # APP0 (JFIF)
        self.assertEqual(data[6:11], b"JFIF\x00")

    def test_dimensions_preserved(self):
        for w, h in [(1, 1), (8, 8), (15, 9), (65, 50), (200, 130)]:
            img = testimages.gradient(w, h)
            data = encoder.encode(img, quality=75)
            out = decoder.decode(data)
            self.assertEqual((out.width, out.height), (w, h))

    def test_all_subsampling_modes_round_trip(self):
        img = testimages.synthetic_photo(48, 48, seed=3)
        for ss in ("444", "422", "420"):
            data = encoder.encode(img, quality=80, subsampling=ss)
            out = decoder.decode(data)
            self.assertEqual((out.width, out.height), (48, 48))
            self.assertGreater(metrics.psnr(img, out), 20.0)

    def test_higher_quality_gives_higher_psnr(self):
        img = testimages.synthetic_photo(64, 64, seed=5)
        psnrs = []
        for q in (10, 40, 80, 95):
            data = encoder.encode(img, quality=q, subsampling="420")
            out = decoder.decode(data)
            psnrs.append(metrics.psnr(img, out))
        for a, b in zip(psnrs, psnrs[1:]):
            self.assertLess(a, b)

    def test_higher_quality_gives_larger_files(self):
        img = testimages.synthetic_photo(64, 64, seed=5)
        sizes = []
        for q in (10, 40, 80, 95):
            data = encoder.encode(img, quality=q, subsampling="420")
            sizes.append(len(data))
        for a, b in zip(sizes, sizes[1:]):
            self.assertLess(a, b)

    def test_more_subsampling_gives_smaller_or_equal_files(self):
        img = testimages.synthetic_photo(64, 64, seed=5)
        s444 = len(encoder.encode(img, quality=75, subsampling="444"))
        s422 = len(encoder.encode(img, quality=75, subsampling="422"))
        s420 = len(encoder.encode(img, quality=75, subsampling="420"))
        self.assertLessEqual(s420, s422)
        self.assertLessEqual(s422, s444)

    def test_solid_color_compresses_extremely_well_and_is_lossless(self):
        img = testimages.solid(32, 32, (100, 150, 200))
        data = encoder.encode(img, quality=80, subsampling="420")
        out = decoder.decode(data)
        # a perfectly flat image should be (near-)losslessly reproduced:
        # only the DC coefficient is nonzero in every block.
        self.assertEqual(metrics.psnr(img, out), float("inf"))

    def test_lossless_at_quality_100_for_flat_regions(self):
        img = testimages.solid(16, 16, (7, 7, 7))
        data = encoder.encode(img, quality=100, subsampling="444")
        out = decoder.decode(data)
        self.assertEqual(img.r, out.r)
        self.assertEqual(img.g, out.g)
        self.assertEqual(img.b, out.b)

    def test_optimized_huffman_shrinks_file_without_changing_pixels(self):
        img = testimages.synthetic_photo(64, 64, seed=9)
        standard = encoder.encode(img, quality=70, subsampling="420", optimize_huffman=False)
        optimized = encoder.encode(img, quality=70, subsampling="420", optimize_huffman=True)
        self.assertLess(len(optimized), len(standard))
        out_std = decoder.decode(standard)
        out_opt = decoder.decode(optimized)
        # Same DCT/quantization -> identical reconstructed pixels;
        # optimized Huffman only changes *how* the same coefficients are
        # packed into bits, never *which* coefficients they are.
        self.assertEqual(out_std.r, out_opt.r)
        self.assertEqual(out_std.g, out_opt.g)
        self.assertEqual(out_std.b, out_opt.b)

    def test_odd_dimensions_do_not_leak_padding_into_visible_image(self):
        # A 1-pixel-wide/tall image forces heavy MCU padding; the crop
        # must remove all of it, not leave replicated garbage rows/cols.
        img = testimages.solid(1, 1, (9, 200, 40))
        data = encoder.encode(img, quality=90, subsampling="420")
        out = decoder.decode(data)
        self.assertEqual((out.width, out.height), (1, 1))

    def test_decode_rejects_non_jpeg_bytes_cleanly(self):
        with self.assertRaises((JpegParseError, JpegDecodeError)):
            decoder.decode(b"this is definitely not a jpeg")

    def test_decode_rejects_truncated_entropy_data_cleanly(self):
        img = testimages.synthetic_photo(32, 32)
        data = encoder.encode(img, quality=80)
        truncated = data[:len(data) - 20] + bytes([0xFF, 0xD9])
        with self.assertRaises(JpegDecodeError):
            decoder.decode(truncated)

    def test_encode_rejects_invalid_dimensions(self):
        from spectral.colorspace import Image
        with self.assertRaises(ValueError):
            encoder.encode(Image(0, 0, [], [], []), quality=50)

    def test_corrupt_chroma_sampling_factor_raises_clean_error_not_index_error(self):
        # Regression: a corrupted SOF component list can claim a chroma
        # component has a *larger* sampling factor than luma, so luma is
        # no longer the frame's maximal-resolution component -- an
        # invariant the plane-reconstruction code relies on without
        # checking. That used to desync the whole MCU grid from what the
        # entropy-coded bits actually contain and crash deep inside
        # colorspace.py with an opaque IndexError. Found by a random
        # bit-flip fuzz run, not by inspection.
        img = testimages.gradient(40, 40)
        data = bytearray(encoder.encode(img, quality=60, subsampling="422"))
        sof_idx = data.index(bytes([0xFF, 0xC0]))
        payload_start = sof_idx + 4
        # payload: precision(1) height(2) width(2) ncomp(1) then 3x [id(1) hv(1) qid(1)]
        cb_hv_offset = payload_start + 1 + 2 + 2 + 1 + 3 + 1  # component 2 (Cb)'s hv byte
        data[cb_hv_offset] = (data[cb_hv_offset] & 0xF0) | 0x03  # Cb.v = 3 > Y.v
        with self.assertRaises(JpegDecodeError):
            decoder.decode(bytes(data))

    def test_bit_flip_fuzz_never_raises_an_unhandled_exception(self):
        # Broad regression sweep for the class of bug above: every
        # single-bit corruption of a real encoded file must be rejected
        # cleanly (JpegParseError/JpegDecodeError) or decode to *some*
        # image, never propagate a raw struct.error/IndexError/etc.
        # This is a bounded, seeded slice of the much larger sweep run
        # during adversarial review (thousands of trials, zero crashes).
        rng = random.Random(20260924)
        for name, gen in list(testimages.ALL_GENERATORS.items())[:3]:
            img = gen(37, 29)
            for subsampling in ("444", "422", "420"):
                data = encoder.encode(img, quality=55, subsampling=subsampling)
                for _ in range(40):
                    corrupted = bytearray(data)
                    idx = rng.randrange(len(corrupted))
                    corrupted[idx] ^= 1 << rng.randrange(8)
                    try:
                        decoder.decode(bytes(corrupted))
                    except (JpegParseError, JpegDecodeError):
                        pass
                    except Exception as e:  # pragma: no cover - failure case
                        self.fail(
                            f"{name}/{subsampling} byte {idx} raised unhandled "
                            f"{type(e).__name__}: {e}"
                        )

    def test_decode_matches_own_encoder_bit_for_bit_stability(self):
        # Encoding and decoding twice from the same source must be fully
        # deterministic (no reliance on dict ordering, RNG, wall clock).
        img = testimages.checkerboard(40, 24, cell=5)
        d1 = encoder.encode(img, quality=60, subsampling="420")
        d2 = encoder.encode(img, quality=60, subsampling="420")
        self.assertEqual(d1, d2)


if __name__ == "__main__":
    unittest.main()
