# Cinch

A from-scratch data-compression toolkit in pure Python (stdlib only).

> **Status:** Phase 2 (core build) complete. All 4 required features +
> the range-coder stretch feature work end-to-end and round-trip. See `PLAN.md`.

## Quick start
```
python3 cli.py bench                 # ratio table vs zlib/bz2/lzma
python3 cli.py roundtrip <file>      # verify every method on a file
python3 cli.py compress <file>       # -> <file>.cinch  (auto-picks best method)
python3 cli.py decompress <file.cinch>
python3 cli.py inspect <file.cinch>
python3 cli.py demo
```

Cinch implements the real algorithms behind modern compressors — canonical
Huffman, LZ77, a DEFLATE-style combined codec, and an adaptive range
(arithmetic) coder — with a self-describing, CRC-checked container format and
a verified round-trip test harness. The standard library's `zlib`/`bz2`/`lzma`
are used only as an external ratio yardstick, never inside the codecs.

Full usage and feature list will land at Phase 6 (ship).
