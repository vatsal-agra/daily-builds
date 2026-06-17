# Shannon

A from-scratch lossless **data-compression toolkit** in pure Python (stdlib only).

> **Status:** Phase 1 (PLAN) complete. See [PLAN.md](PLAN.md) for the full design.

Shannon implements the three pillars of real compressors — entropy coding
(Huffman + arithmetic), dictionary coding (LZ77/LZSS), and reversible transforms
(Burrows–Wheeler + MTF + RLE) — and composes them into named codecs over a real
`.shz` container format with CRC self-verification. Correctness is proven by
round-trip equality and measured against the Shannon entropy bound.

Build phases (per the daily-build process):
1. ✅ **Plan** — concept, architecture, ≥6 features.
2. ⬜ Core build — Huffman, arithmetic coder, LZ77, BWT pipeline.
3. ⬜ Adversarial review + fixes.
4. ⬜ Stretch (entropy report, HTML viz) + polish.
5. ⬜ Verification suite.
6. ⬜ Ship.
