# Adversarial Review — Shannon

I attacked my own toolkit as a hostile reviewer, focusing on the decoder (which
must survive arbitrary/corrupt input) and on the round-trip contract. The
round-trip property is a perfect oracle, so correctness bugs surface immediately;
the interesting failures were all on the *corrupt-input* surface.

## Findings

### 1. CRITICAL — decompression bomb / OOM on corrupt headers
**Symptom:** feeding randomly-corrupted `.shz` blobs to `unpack` killed the
Python process (exit 137). **Cause:** the header `orig_len`, the BWT `nblocks`,
and the BWT `huff_count` are all read as varints and then trusted as loop/alloc
bounds. A few flipped bytes can encode a 10¹²-ish value, so the decoder tried to
allocate gigabytes or loop billions of times before any CRC check could run.
**Fix:**
- A hard `MAX_DECOMPRESSED = 1 GiB` ceiling on `orig_len`, checked *before* any
  work (`container.py`). The crafted 10¹²-byte bomb is now rejected in ~0 ms.
- `nblocks` is fully determined by `orig_len`; the decoder now recomputes the
  expected value and rejects a mismatch instead of looping on the stored count.
- `huff_count` (post-RLE symbol count) is bounded by `2·orig_len + 64` (RLE can
  expand by at most ~5/4), rejecting implausible values.

### 2. BUG — corrupt payloads raised uncaught low-level exceptions
**Symptom:** corrupting the payload of a valid container raised
`IndexError`/`KeyError` (e.g. an out-of-range MTF rank, a BWT row past the end,
a varint reading past EOF) instead of a clean, catchable error. A library should
report "corrupt stream", not leak an arbitrary internal exception. **Fix:**
`container.unpack` now wraps the codec decode and normalizes
`IndexError/KeyError/OverflowError/MemoryError/RecursionError` into a single
`ValueError("corrupt .shz payload …")`; a truncated header likewise raises a
clean `ValueError`.

### 3. Verified — no *silent* corruption slips through
After the fixes I threw 750 corrupted/truncated blobs (bit-flips + truncations)
at all five compressing codecs: **0 uncaught crashes, 0 cases of wrong output
returned as if valid.** Everything is either decoded correctly (when the
corruption hit padding/no-op bits) or rejected by the structural checks or the
final CRC. The CRC is the backstop that makes "decode succeeded" trustworthy.

## Things I checked and found already correct
- **Round-trip across 6,000 fuzzed inputs** (small alphabets, run-heavy,
  text-like, pure random; lengths 0–400) × all codecs: 0 mismatches.
- **Edge inputs** — empty, single byte, single repeated symbol, all-256-bytes —
  round-trip on every codec (single-symbol Huffman correctly forced to length 1;
  arithmetic decode of 0 symbols returns empty).
- **Multi-block BWT** — a 179 KB input spans 6 BWT blocks and round-trips; the
  `--best` path always includes `store`, so output can never expand beyond the
  ~11-byte container overhead.
- **Arithmetic-coder arithmetic** — `MAX_TOTAL = 2¹⁶ ≪ 2³⁰`, so the
  `range·cum//total` updates never underflow the WNC interval invariant.

## Known, accepted limitations (documented, not bugs)
- **MTF is O(256·n)** (`list.index`/`pop`/`insert`), so `bwt` is the slowest
  codec (~1 s/200 KB). Fine for the toolkit's target sizes; a fixed-size linked
  table would speed it up and is listed as future work.
- **`info`/`decompress` fully decode** to verify the CRC before reporting — this
  is deliberate (the integrity line is then truthful) but means `info` is O(file).
- The 1 GiB ceiling is an absolute guard; within it a maliciously-crafted (but
  CRC-consistent) high-ratio stream could still be large to expand. That is
  inherent to any compressor and bounded here by the cap.
