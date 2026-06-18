# Cinch — Adversarial Review

Attacking my own work as a hostile reviewer. Each issue is listed with its
status; everything marked **FIXED** has a verifying check in `tests.py`.

## Bugs found *during* the core build (caught by my own round-trip gate)

### B1 — Single-symbol Huffman tree desynced the DEFLATE bitstream  *(FIXED)*
**Severity: critical (silent data corruption).**
A canonical tree with exactly one symbol assigns it a real 1-bit code, so the
encoder writes 1 bit. My `CanonicalDecoder` had a "single symbol" shortcut that
returned the symbol while reading **zero** bits. In standalone Huffman this was
invisible (output length is driven by the symbol count), but in DEFLATE the
literal/length and distance streams are *interleaved*, so the missing bit
desynced everything downstream. Symptom: `b"a"*5000` decoded to 10160 bytes.
**Fix:** removed the shortcut; the normal canonical path consumes the bit. Any
single-symbol run now round-trips. Regression: `test_single_symbol_streams`.

### B2 — Corrupt input raised raw `EOFError` instead of a clean error  *(FIXED)*
Flipping a payload byte could make a codec read past the end and raise
`EOFError`/`IndexError`, leaking an implementation exception. **Fix:**
`decompress` now wraps codec decode in a `try/except` that converts
`EOFError/ValueError/IndexError` into `CinchError("corrupt payload: ...")`.

## Bugs found in the dedicated review pass

### B3 — Truncated container header raised raw `ValueError`  *(FIXED)*
A blob with a valid 11-byte magic+method+CRC prefix but a missing/short
`origlen` varint reached `read_uvarint`, which raised a bare `ValueError`
("truncated varint") out of both `decompress` and `inspect`. A well-behaved
library should report one error type for all malformed input.
**Fix:** header parsing in `decompress` and `inspect` is wrapped to raise
`CinchError`. Regression: `test_malformed_containers`.

### B4 — `bench` could divide by zero / show noise on empty corpus member  *(FIXED)*
The empty input has size 0; ratio computation guarded with `if data else 0.0`,
but I confirmed every code path (`compress`, `inspect`, CLI messages) handles
zero-length input without `ZeroDivisionError`. Verified by
`test_empty_everywhere`.

### B5 — Corrupt input could make the decoder **hang forever**  *(FIXED)*
**Severity: high (denial of service on malformed input).**
The range coder is self-terminating: it decodes symbols until it sees the EOF
symbol (256). Feed it a corrupted stream where EOF never appears and the
decoder happily reads its *infinite zero padding* past end-of-data, decoding
bytes forever — `decompress` never returns. (A corrupted length varint in the
other codecs is bounded by the payload, but is wasteful.) Found by my own
`test_corruption_detected` **timing out at 90s** instead of passing.
**Fix:** every codec decoder now takes a `limit` and the container passes the
true `origlen` from its header; output that exceeds the limit raises, so corrupt
data fails fast (the corruption test now runs in ~2s). Regressions:
`test_corrupt_length_field_no_hang` plus the existing corruption sweep.

## Weaknesses considered and judged acceptable (documented, not bugs)

- **DEFLATE can lose to bare LZ77 on tiny, ultra-repetitive inputs.** Two
  dynamic Huffman trees cost header bytes; when the token stream is already
  ~100 bytes that header dominates. This is real and correct behaviour — the
  `auto` method exists precisely to pick the smallest, and it does. Not a bug.
- **Range coder is O(alphabet) per symbol** (linear cumulative-frequency scan).
  Fine for the corpus; for multi-MB inputs it is slow. Documented as a known
  limitation and a natural "where to take this next" (Fenwick-tree model).
- **`store` guarantees output ≤ input + ~12 bytes**, so `auto` never expands a
  file by more than the container header. Verified by `test_auto_never_worse`.

## Adversarial fuzzing performed
- 20,000 random byte strings (random length 0–1024, random alphabets including
  binary, skewed, and single-value) round-tripped through **every** method via
  the container (CRC-checked). Zero failures — see `test_fuzz_all_methods`.
- Every byte position of several compressed files flipped (1216 flips): 0
  silently-wrong decodes; all detected by CRC or rejected as corrupt.
- Canonical-code invariants (prefix-free, Kraft sum ≤ 1, length ≤ 15) asserted
  on the actual 286- and 30-symbol DEFLATE alphabets over random frequencies.
