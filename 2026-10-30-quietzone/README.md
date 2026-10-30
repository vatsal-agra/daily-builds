# Quietzone

A from-scratch **QR code laboratory** in Go (standard library only, ~4,900 lines + ~1,650 lines of tests).
It encodes QR symbols to the ISO/IEC 18004 spec, decodes them, **finds and reads them in rotated,
tilted, blurred, noisy photographs**, and lets you break them on purpose to see exactly how Reed–Solomon
error correction saves (or fails to save) the data.

Everything is implemented here: GF(256) arithmetic, Reed–Solomon encoding and full error-*and*-erasure
decoding (Berlekamp–Massey / Chien / Forney), BCH format and version codes, optimal mode segmentation
(dynamic programming), mask scoring, finder-pattern detection, projective geometry (least-squares
homography), adaptive thresholding.

```
$ qz encode -ecc Q "https://example.com"          # terminal art
$ qz distort -roll 37 -tiltx 28 -blur 1.3 -noise 14 -jpeg 40 code.png photo.png
$ qz scan photo.png                                # reads it back, reports repairs
$ qz damage -ecc H -logo 0.25 "..."                # blank 25 % of the width, recover via erasures
$ qz html -o anatomy.html "..."                    # interactive anatomy / corruption explorer
```

## Run it

```bash
go build -o qz ./cmd/qz        # needs Go 1.24+, nothing else
./qz help
./verify.sh                    # gofmt, vet, all tests, benchmark floors, CLI demo, cross-check
./verify.sh --mutate           # ...plus the mutation harness (a few minutes)
```
`verify.sh` uses Node + Playwright (HTML explorer test) and Python 3.13 with `segno` + `opencv` (independent
cross-checks) when present, and skips those parts politely when not.

## Features

**Core (required)**
1. **Reed–Solomon over GF(256)** — encoder and decoder correcting `2·errors + erasures ≤ parity`; fuzzed to the exact theoretical limit; failed decodes never mutate the block.
2. **QR encoder** — versions 1–40, ECC L/M/Q/H, numeric / alphanumeric / byte / ECI modes, **optimal segmentation by DP**, 8 masks scored by the N1–N4 rules, PNG / SVG / terminal half-block output. Byte-identical to `segno` on random symbols; readable by OpenCV.
3. **Matrix decoder** — BCH-corrects the format word (both copies, with a brute-force fallback over all 32 level/mask pairs), de-interleaves, runs RS per block, parses segments (numeric/alnum/byte/ECI/structured append/FNC1), recovers mirrored symbols, accepts an *erasure map* (e.g. a logo).
4. **Image scanner** — Bradley adaptive + Otsu + denoised + inverted binarisation tiers, 1:1:3:1:1 finder detection, rotation-invariant module size, finder ring corners + alignment patterns fed to a least-squares homography, version found by scoring the **timing pattern** (no trust in pixel distances), multiple symbols per image.

**Stretch (shipped)**
5. `qz damage` — random / logo damage, per-block budget report, **erasure decoding** of the logo, `-sweep` resilience table per ECC level.
6. Multi-symbol scanning, plus **structured append** (`encode -parts N`; scan reassembles and checks parity).
7. `qz html` — **anatomy explorer**: roles, RS blocks, codeword order, click-to-corrupt with a live "still scans?" verdict per block. The page's verdict is cross-checked against the Go decoder in headless Chromium (zero disagreements over 360 damage patterns).
8. Payload builders (`WIFI:` with correct escaping, `mailto:`, vCard), `qz rs` Reed–Solomon workbench, `qz explain` (blocks, bit budget, all 8 mask penalties), `qz distort` camera simulator, `qz bench` accuracy benchmark.

## Numbers (all reproducible; `qz bench -n 36`)

| scenario | pass |
|---|---|
| clean, rotation 0–360°, mirrored | 100 % |
| tilt ≤ 35°, strong tilt 35–65° | 100 % |
| blur σ=1.5px, noise σ=25 + salt&pepper, JPEG q20 | 100 % |
| uneven light + low contrast, background clutter | 100 % |
| 3-px modules, v25–40 rotated, 14 %-wide logo | 100 % |

Typical scan time 5–75 ms. Cross-check: OpenCV reads 40/40 of our symbols; we read 40/40 of segno's and 40/40
of segno's after distortion. Mutation testing: 19/20 injected bugs killed (the survivor is provably redundant).
Resilience (v6, random module flips): L ≈ 1.2 %, M 1.9 %, Q 3.1 %, H 3.6 % of data modules survive.

## Why I built this today

The repo already had compression, crypto, DNS, TLS, filesystems, compilers — but nothing in the family of
**error-correcting codes** or **machine-readable symbols**, and QR is the one ECC system everyone has used and
almost nobody has opened. It also closes a loop that makes every claim measurable: the encoder is ground
truth, a camera simulator wrecks it in controlled ways, and the scanner must recover it. The adversarial phases
found real defects that only an independent oracle could expose (a non-conformant mask penalty that produced
*valid* symbols — see [REVIEW.md](REVIEW.md)).

## Layout
`qr/` GF, RS, tables, segments, encoder, decoder, rendering · `scan/` binarise, finders, homography, scanner ·
`sim/` camera simulator · `bench/` accuracy suite · `cmd/qz/` CLI + HTML explorer · `tools/` cross-check, mutation
harness, browser check · [PLAN.md](PLAN.md) · [REVIEW.md](REVIEW.md)

## Known limits
Kanji/Hanzi mode decoding and Micro/rMQR symbols are not implemented (the decoder says so explicitly);
curved surfaces are out of scope (projective model only); a 6-megapixel pure-noise image takes ~6 s to reject.

## Where a human could take this next
* Kanji mode (needs a Shift-JIS table), Micro QR and rMQR.
* Local sampling-grid refinement (piecewise homography / thin-plate) for curved labels.
* Soft-decision decoding: feed per-module confidence to RS as erasures — the decoder already accepts erasure maps, the scanner just doesn't produce them yet.
* A WASM build of the scanner + the explorer for a camera-driven web demo.
* Reed–Solomon list decoding (Guruswami–Sudan) to go beyond `ecc/2`.
