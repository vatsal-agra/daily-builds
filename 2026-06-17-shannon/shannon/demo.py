"""Self-checking end-to-end demonstration (`shannon demo`).

Runs real data through every codec, verifies each round-trips byte-for-byte and
passes its CRC, prints the analysis report, and asserts the properties we claim
(arithmetic beats Huffman on text, dictionary coding wins on repetitive data,
nothing expands past the container overhead, corruption is detected). Returns 0
on success, 1 on any failure — so it doubles as a smoke test.
"""
from __future__ import annotations

import random

from . import analyze, codecs, container

SAMPLES = {
    "english text": (
        b"the quick brown fox jumps over the lazy dog. " * 12
        + b"pack my box with five dozen liquor jugs. " * 12),
    "source-like": (
        b"def compress(data):\n    return encode(data)\n" * 20),
    "very repetitive": b"ABCABCABC" * 400,
    "long run": bytes([0]) * 2000,
    "random bytes": bytes(random.Random(7).randbytes(2000)),
    "all 256 bytes": bytes(range(256)) * 6,
}


def run() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        status = "ok  " if cond else "FAIL"
        if not cond:
            failures += 1
        print(f"  [{status}] {msg}")

    print("=" * 64)
    print("Shannon self-checking demo")
    print("=" * 64)

    for label, data in SAMPLES.items():
        print(f"\n### {label}  ({len(data)} bytes)")
        sizes = {}
        for name in codecs.ALL_NAMES:
            blob = container.pack(name, data)
            back = container.unpack(blob)
            sizes[name] = len(blob)
            check(back == data, f"{name:8s} round-trips ({len(blob)} bytes)")
        # nothing should expand beyond store + a little container overhead
        check(min(sizes.values()) <= len(data) + 16,
              "best codec does not expand the data")

    # Property checks on text vs repetitive inputs.
    text = SAMPLES["english text"]
    rep = SAMPLES["very repetitive"]
    s_text = {n: len(container.pack(n, text)) for n in codecs.ALL_NAMES}
    s_rep = {n: len(container.pack(n, rep)) for n in codecs.ALL_NAMES}
    print("\n### property checks")
    check(s_text["arith0"] <= s_text["huffman"],
          "arithmetic ≤ Huffman on text (no-integer-bit advantage)")
    check(s_text["arith1"] < s_text["arith0"],
          "order-1 model beats order-0 on text")
    check(s_rep["lz77"] < s_rep["huffman"],
          "dictionary coding beats pure entropy coding on repetitive data")

    # Integrity: a single flipped payload byte must be detected.
    blob = bytearray(container.pack("bwt", text))
    blob[-1] ^= 0xFF
    detected = False
    try:
        container.unpack(bytes(blob))
    except ValueError:
        detected = True
    check(detected, "corrupted archive is rejected (CRC / structure check)")

    # Decompression-bomb guard.
    bomb = bytearray(b"SHZ1\x01\x02")
    v = 10 ** 12
    while True:
        byte = v & 0x7F
        v >>= 7
        bomb.append(byte | 0x80 if v else byte)
        if not v:
            break
    bomb += b"\x00\x00\x00\x00"
    rejected = False
    try:
        container.unpack(bytes(bomb))
    except ValueError:
        rejected = True
    check(rejected, "decompression bomb (huge declared size) is rejected")

    print("\n" + "-" * 64)
    print(analyze.report(text, label="english text sample"))
    print("-" * 64)
    if failures:
        print(f"\nDEMO FAILED: {failures} check(s) failed")
        return 1
    print("\nDEMO PASSED: all checks green")
    return 0
