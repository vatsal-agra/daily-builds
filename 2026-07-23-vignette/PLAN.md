# Vignette — a from-scratch lossy image codec

## Concept

Build a real baseline JPEG-style image compressor and decompressor, from first
principles, in pure Python (stdlib only — no PIL, no numpy). Every stage of
the classic lossy transform-coding pipeline gets implemented by hand:

`RGB → YCbCr → 4:2:0 chroma subsampling → 8×8 block split → 2D DCT-II →
quantization → zigzag scan → DPCM (DC) + RLE (AC) → Huffman entropy coding →
real JFIF/JPEG file bytes`

and the inverse all the way back to pixels. The encoder writes **actual
standard-compliant baseline JPEG files** — the kind any image viewer, browser,
or `file`/`identify` utility recognizes — not a private container format.
That's the harder and more interesting target: it forces exact conformance
to ITU-T T.81 (marker structure, zigzag order, standard Huffman/quant
tables, MCU interleaving) rather than an easier made-up format.

## Why this is interesting

Every previous build in this repo that touched compression did *lossless*,
general-purpose coding (Huffman/LZ77/BWT — Cinch, Shannon) or a *lossy 3D
renderer* (Prism, Lumen, Lumina, Pathtracer) or *lossless-only* image
analysis (Optic's CV pipeline). None of them implement **transform coding**:
turning spatial pixel blocks into frequency coefficients, throwing away the
perceptually unimportant high-frequency ones via quantization, and coding
what's left — which is the actual idea that makes JPEG, MPEG, and every
modern video/audio codec (including music/video streaming, webcams, and
browser <img> tags) possible. It's also self-verifying in a satisfying way:
the DCT is orthogonal (a mathematical fact you can test), and the final file
format is a real published international standard, so "did I get it right"
has an objective, external answer — not just "does it look plausible."

## Architecture

```
vignette/
  image.py      — minimal RGB image container; PPM (P6) read/write;
                   procedural test-image generators (gradients, checkerboards,
                   circles, plasma/photo-like noise, text bars) so the whole
                   pipeline is testable without needing external image files
  png.py         — from-scratch PNG encoder (zlib deflate via the stdlib
                   `zlib` module, hand-built chunk/CRC framing) — used only
                   to render human-viewable output (originals, reconstructions,
                   diff maps, DCT heatmaps) into the HTML report/visualizer
  dct.py         — separable 2D DCT-II / inverse DCT-II over 8×8 blocks,
                   built from the closed-form basis functions; includes a
                   brute-force O(N^4) reference implementation used only in
                   tests to cross-check the fast separable version
  tables.py      — the real ITU-T T.81 Annex K standard luminance/chrominance
                   quantization tables and the standard (Annex K.3) Huffman
                   code tables, plus quality-factor scaling (libjpeg's
                   IJG scaling formula)
  huffman.py     — canonical Huffman code builder from code-length counts +
                   symbol lists (used both to consume the standard JPEG
                   tables and, for the stretch feature, to build optimal
                   per-image tables), plus a bit-level writer/reader with
                   JPEG's 0xFF byte-stuffing rule
  encoder.py     — full pipeline: image -> valid baseline JFIF `.jpg` bytes
  decoder.py     — full inverse pipeline: JFIF bytes -> reconstructed image;
                   parses real marker segments (SOI/APP0/DQT/SOF0/DHT/SOS/EOI)
  metrics.py     — PSNR and windowed SSIM between two images, compression
                   ratio / bits-per-pixel reporting
  cli.py         — `vignette encode|decode|analyze|compare` command-line tool
  visualize.py   — generates a self-contained interactive HTML report:
                   quality slider (pre-rendered ladder of qualities),
                   size/PSNR/SSIM curves, and a DCT coefficient heatmap panel
tests/
  test_dct.py, test_huffman.py, test_tables.py, test_codec.py, test_png.py
demo.sh          — end-to-end runnable demonstration + test suite runner
```

## Feature list

1. **[required] Full baseline JPEG encoder producing real, spec-valid JFIF
   files.** RGB→YCbCr, 4:2:0 chroma subsampling with correct MCU padding for
   arbitrary (non-multiple-of-16) image sizes, per-block 2D DCT-II,
   quality-scaled standard quantization tables, zigzag scan, DC
   delta-encoding, AC zero-run-length + size-category encoding, standard
   Huffman entropy coding with proper 0xFF00 byte stuffing, and correct
   marker segment writing (SOI, APP0/JFIF header, DQT×2, SOF0, DHT×4, SOS,
   entropy-coded scan data, EOI). Verified as a real JPEG by the system
   `file` utility (independent external oracle, not our own code) and by our
   own from-scratch decoder.

2. **[required] Full baseline JPEG decoder.** Parses marker segments from
   scratch, Huffman-decodes the entropy stream, reconstructs zigzag→8×8
   dequantized coefficient blocks, applies inverse DCT, upsamples chroma,
   converts YCbCr→RGB, and reassembles the image — including handling
   restart-free baseline scans and correct MCU/block geometry for
   subsampled images. Round-trips our own encoder's output and is checked
   against a brute-force reference DCT implementation for numerical
   correctness.

3. **[required] Quality/rate-distortion analysis toolkit.** Adjustable JPEG
   quality factor (1–100) using the real IJG quality-to-quantization-table
   scaling formula; PSNR and windowed SSIM computation between original and
   reconstructed images; a size-vs-quality and PSNR-vs-quality curve;
   bits-per-pixel and compression-ratio reporting, all exposed through the
   CLI (`vignette analyze`) and rendered into the HTML report.

4. **[required] Interactive HTML visualizer.** A single self-contained HTML
   report (`visualize.py`) showing, per test image: a quality slider that
   swaps between pre-rendered PNG reconstructions at multiple quality
   levels, live file-size/PSNR/SSIM readouts per quality step, a
   side-by-side original-vs-compressed zoom panel to see 8×8 blocking
   artifacts at low quality, and a DCT coefficient magnitude heatmap for a
   selected block.

5. **[stretch] Optimal per-image Huffman tables.** Instead of the fixed
   standard tables, compute actual symbol-frequency-driven canonical Huffman
   tables per image (still spec-legal — baseline JPEG allows custom DHT
   segments) and report the extra bits saved vs. the standard tables.

6. **[stretch] Quality ladder / artifact gallery + progressive refinement
   demo.** Batch-render every test image at qualities 100→5 and produce a
   gallery page demonstrating the classic JPEG artifact progression
   (blocking, ringing, color bleed) with size numbers annotated — a visual,
   quantitative demonstration of the rate-distortion tradeoff the codec
   implements.

## Verification strategy

- DCT correctness: fast separable implementation checked element-by-element
  against a brute-force O(N^4) direct-sum reference over random blocks, plus
  an orthogonality/round-trip identity test (IDCT(DCT(x)) == x within float
  tolerance).
- Huffman correctness: canonical code construction checked against known
  ITU-T Annex K.3 table values; encode/decode bit-stream round trip test.
- Codec correctness: encode→decode round trip PSNR must clear a
  quality-dependent threshold on every procedural test image; produced files
  are validated as real JPEGs by the external `file` command.
- No mocked stages: every pixel that comes out of the decoder is produced by
  running the actual inverse math over the actual entropy-decoded
  coefficients — nothing is precomputed or faked for the demo.
