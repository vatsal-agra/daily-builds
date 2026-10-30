# Quietzone — Plan

## Concept
A from-scratch **QR code laboratory in Go** (stdlib only): encode text into spec-conformant QR symbols
(ISO/IEC 18004, versions 1–40, ECC L/M/Q/H), decode them back from a *module matrix*, and — the hard
part — decode them from **photographs-like images** (rotated, perspective-warped, blurred, noisy, with a logo
punched out of the middle). Everything under the hood is implemented here: GF(256) arithmetic,
Reed–Solomon encode and full error-*and*-erasure decode (Berlekamp–Massey, Chien, Forney), BCH format/version
codes, mask scoring, optimal mode segmentation, finder-pattern detection, homography estimation.

## Why it is interesting
* The repo has compression, crypto, DNS, TLS, FS, CV … but never **error-correcting codes** nor a
  **machine-readable-symbol** pipeline. QR is the one ECC system everybody has used and nobody has opened.
* It closes a loop: the encoder produces ground truth, a distortion simulator wrecks it in controlled ways,
  and the scanner must recover it — so every accuracy claim is measurable, not asserted.
* Real algorithmic content: a DP that picks the cheapest numeric/alnum/byte segmentation, decoder-side
  syndrome decoding that can fix `t = ecc/2` unknown errors or `ecc` known erasures, projective geometry.

## Architecture
```
qr/    gf.go rs.go        GF(2^8) over 0x11D, polynomial ops, RS encoder + BM/Chien/Forney decoder
       tables.go          ECC block tables, capacities, alignment positions (validated by tests)
       segment.go         numeric/alnum/byte/ECI modes, optimal segmentation (DP), bit packing
       layout.go          function-pattern map, zig-zag data order, format/version BCH
       encode.go mask.go  data+ECC interleave, placement, 8 masks, N1–N4 penalty scoring
       decode.go          matrix -> format (BCH correct) -> unmask -> deinterleave -> RS -> segments
       render.go          text / SVG / PNG output
scan/  binarize.go        Bradley adaptive threshold (integral image)
       finder.go          1:1:3:1:1 run-length detection in rows+cols, clustering, triple selection
       homography.go      8-DoF projective transform solved by Gaussian elimination
       scan.go            version estimate, alignment-pattern refinement, grid sampling, retry strategy
sim/   warp.go            rotation / perspective / blur / noise / logo / invert-contrast simulators
cmd/qz encode | decode | scan | damage | explain | html | rs | bench
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | GF(256) + Reed–Solomon encoder and full decoder (errors + erasures, BM/Chien/Forney) | **required** |
| 2 | QR encoder: v1–40, L/M/Q/H, numeric/alnum/byte/ECI, optimal segmentation, mask selection, PNG/SVG/text | **required** |
| 3 | Matrix decoder: BCH format/version recovery, de-interleave, RS correction, segment parsing, error report | **required** |
| 4 | Image scanner: adaptive binarize, finder detection, homography, alignment refinement, sampling, retries | **required** |
| 5 | Distortion simulator + `damage` tool (flip N modules / erase a logo; shows error budget used) | stretch |
| 6 | Multi-code scan (several symbols in one image) | stretch |
| 7 | HTML anatomy explorer (function patterns, data/ECC blocks colour-coded, click-to-corrupt live) | stretch |
| 8 | Payload helpers (WIFI:, mailto:, vCard validators) and Structured Append | stretch |

## Verification strategy
Unit tests against independent oracles (known capacities, spec worked example "01234567" v1-M, differential
vs. Python `qrcode`/`segno` if available), RS fuzz against brute-force bounds, end-to-end
encode→distort→scan accuracy matrix with floors, CLI demo script, mutation spot-checks.
