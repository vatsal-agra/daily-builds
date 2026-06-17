# Cinch

A from-scratch data-compression toolkit in pure Python (stdlib only).

> **Status:** Phase 1 (planning) complete. See `PLAN.md`.

Cinch implements the real algorithms behind modern compressors — canonical
Huffman, LZ77, a DEFLATE-style combined codec, and an adaptive range
(arithmetic) coder — with a self-describing, CRC-checked container format and
a verified round-trip test harness. The standard library's `zlib`/`bz2`/`lzma`
are used only as an external ratio yardstick, never inside the codecs.

Full usage and feature list will land at Phase 6 (ship).
