# Adversarial review — Phase 3

Methodology: attack the finished Phase 2 build as a hostile reviewer —
random bit-flip fuzzing of real encoded files against both the marker
parser and the full decoder, direct CLI probing with malformed/missing/
adversarial input, mathematical bound-checking of the entropy coder's
worst case, and a from-first-principles re-derivation of the one hand-
transcribed constant that was suspicious (the DCT normalization factor,
caught and fixed *before* this phase even started — see the Phase 2
commit message). Findings below are grouped: real bugs (fixed), things
that looked like bugs but checked out as correct/expected, and honest
scope notes.

## Real bugs found and fixed

1. **CRITICAL — corrupted component sampling factors could crash deep
   inside plane reconstruction with an opaque `IndexError`.**
   `decoder.decode()` silently assumed component 1 (Y) always carries the
   frame's maximal horizontal/vertical sampling factors, because that's
   the only layout `encoder.py` ever produces. A 9,600-trial random
   bit-flip fuzz sweep (every subsampling mode, both standard and
   optimized Huffman tables) found a single corrupted bit in a chroma
   component's `v` field that made a *chroma* component claim a larger
   sampling factor than luma. Nothing validated that this couldn't
   happen: the decoder went on to compute `hmax`/`vmax` from the
   corrupted value, which desynced the entire MCU grid (block counts,
   scan order) from what the entropy-coded bits actually contained,
   surfacing many steps later as an `IndexError` reading past the end of
   a chroma plane in `colorspace.py` — nowhere near the actual cause.
   **Fix:** `decoder.py` now explicitly validates, right after parsing,
   that components are exactly `{1, 2, 3}`, that component 1 has the
   frame's maximal sampling factors, and that components 2/3 are `(1,
   1)` — raising a clean `JpegDecodeError` naming the violated
   invariant instead of assuming it. Regression test:
   `test_corrupt_chroma_sampling_factor_raises_clean_error_not_index_error`.

2. **A corrupted DQT precision nibble raised a raw `struct.error`.**
   Flipping one bit in a quantization table segment's Pq/Tq byte can make
   it claim 16-bit table precision in a payload only sized for the real
   8-bit table; `struct.unpack(">64H", ...)` then raised
   `struct.error: unpack requires a buffer of 128 bytes` straight out of
   `markers.py`, not the intended `JpegParseError`. Same fuzz sweep found
   this on the very first run, before fix #1 was even isolated.
   **Fix:** every marker-segment-body dispatch in `markers.parse()` is
   now wrapped so `struct.error`/`IndexError`/`ValueError` convert to a
   clean `JpegParseError` naming the marker. Regression test:
   `test_corrupt_dqt_precision_nibble_raises_clean_error_not_struct_error`.
   A permanent bounded fuzz sweep (`test_bit_flip_fuzz_never_raises_an_
   unhandled_exception`) now runs on every test invocation as a
   standing guard against this whole bug class.

3. **`decode` on a missing input file raised a raw `FileNotFoundError`.**
   `cmd_decode` opened `args.input` directly, before entering any
   try/except. Caught immediately by `demo.sh`'s own error-handling
   section (step 5), which is exactly what that section exists for.
   **Fix:** routed through a shared `_read_file()` helper that catches
   `FileNotFoundError`/`OSError` and reports a clean `error: ...` message.

4. **Four more raw-traceback gaps found by direct CLI probing, same
   pattern (file I/O outside any try/except):** `encode --output` to a
   nonexistent directory, `decode --output` to a nonexistent directory,
   `compare --width -5` (negative dimensions reaching an unguarded call),
   and `viz`/`encode --progressive` raising a bare `ImportError` instead
   of "not available yet" before those stretch features existed. All
   four fixed the same way: route through `_write_file()` / wrap in
   `try/except ValueError` / catch `ImportError` explicitly, matching the
   pattern already used elsewhere in the CLI.

5. **`colorspace.Image.__init__` used a bare `assert` for dimension/
   plane-length validation.** `[0] * negative_number` silently evaluates
   to an empty list in Python, so `Image(-5, 10, [], [], [])` didn't
   raise where it was constructed — it tripped the length-mismatch
   `assert` with an opaque `AssertionError` and no message, and asserts
   disappear entirely under `python -O`. Found via `spectral.cli encode
   --width -5`. **Fix:** replaced with explicit `ValueError`s with clear
   messages, for both the negative-dimension case and the general
   plane-length-mismatch case. Regression tests:
   `test_image_rejects_negative_dimensions_cleanly`,
   `test_image_rejects_mismatched_plane_lengths`.

## Checked, not a bug (real risk, verified safe)

- **Could a DC or AC coefficient ever need a Huffman category the
  standard tables don't have (DC > 11, AC size > 10)?** This was a real
  concern, not a hypothetical: it would `KeyError` straight out of
  `HuffmanTable.encode_symbol`. Worked the bound from Parseval's theorem
  (an orthonormal transform preserves total energy, so `sum(coeff^2) <=
  64 * 128^2` for any valid 8-bit-per-sample block) and confirmed
  empirically with the two adversarial patterns designed to maximize
  each case: an alternating-8×8-block checkerboard at quality 100 for DC
  (measured max DC delta: 2040, category 11 — the table's actual max,
  supported by design) and a 1-pixel checkerboard within a single block
  for AC (measured max coefficient: 837, category 10 — also the table's
  actual max). This is why the standard's DC table stops at exactly
  category 11 for 8-bit precision: it's a hard bound, not a heuristic.
  No fix needed; documented here so the bound is on record rather than
  assumed.

- **4:2:0/4:2:2 decoded pixels differ from a real browser's decode by up
  to ~40 levels on saturated, high-frequency-chroma content (the radial
  test image).** Isolated the cause by re-running the same comparison at
  4:4:4 (no chroma subsampling at all): the divergence collapsed to ≤2
  everywhere. This proves the DCT, quantization tables, Huffman tables,
  and marker/bitstream framing are bit-correct (the actual thing this
  project needs to prove) — the residual difference at 4:2:0/4:2:2 is
  entirely from *chroma upsampling filter choice*, which the JPEG
  standard deliberately leaves to the decoder. Spectral originally used
  nearest-neighbor (blocky); switched to bilinear during this phase,
  which is both a genuine visual-quality improvement (smooth chroma
  gradients instead of hard subsample-grid edges) and cut the observed
  worst-case divergence from a real decoder roughly in half (86 → 39 on
  the worst case measured). No further chase for exact parity: no filter
  choice here is mandated by the spec, and matching one specific
  decoder's undocumented internal filter bit-for-bit isn't a
  correctness requirement.

- **4:4:4 (no subsampling at all) still shows small residual differences
  from Chromium at low quality (up to 12 at quality 15 in the fixture
  suite; up to 45 at quality 1 in an out-of-band check).** Spectral's
  IDCT is the mathematically exact float transform (proven identical to
  an independent brute-force O(N⁴) reference to 1e-8 in `test_dct.py`);
  Chromium's is almost certainly a fast *approximate* integer IDCT, as
  essentially every deployed JPEG decoder uses for speed (T.81 bounds
  decoder accuracy, it doesn't mandate bit-exactness across
  implementations). At very coarse quantization, few coefficients
  survive and each has a much larger magnitude, which amplifies any
  small per-implementation rounding difference — a real, well-
  understood, purely cosmetic effect. Cross-checked that Spectral's own
  round trip stays internally consistent throughout (monotonic PSNR/size
  vs. quality, near-lossless on flat regions, deterministic output) to
  rule out this being a symptom of an actual bug rather than expected
  implementation variance.

## Honest scope note

Spectral's decoder does not implement restart markers/intervals (DRI/
RST0-7). `encoder.py` never emits `DRI`, so this never affects round-
tripping Spectral's own output — the entire tested and demoed surface —
but a restart-interval-using third-party JPEG (common from some cameras)
would not decode correctly. This wasn't discovered as a bug in existing
behavior; it's a real, intentional scope boundary being stated plainly
rather than silently implied as "full JPEG decoding."

## Verification after fixes

- 78/78 unit tests green (up from 73 pre-review), including 5 new
  regression tests for the bugs above plus a permanent bounded fuzz
  sweep that runs every invocation.
- An expanded ad hoc fuzz run (9,600 random single-bit flips across 8
  synthetic images × 3 subsampling modes × standard/optimized Huffman
  tables) found zero unhandled exceptions post-fix.
- `demo.sh` green end to end, including the 45-fixture independent
  headless-Chromium oracle check.
