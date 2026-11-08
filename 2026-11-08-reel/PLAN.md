# Reel — PLAN

## Concept
**Reel** is a from-scratch **hybrid video codec** (the H.264/AVC family of ideas) written in Go with
the standard library only: an encoder, a decoder, a bitstream container, a procedural test-video
generator, quality metrics, and an HTML rate–distortion lab. It is the repo's first *video* /
*motion-compensated prediction* build — the repo already has a JPEG-style still-image codec,
DEFLATE, audio fingerprinting and a PDF renderer, but nothing that exploits **time**.

## Why it is interesting
A video codec is a closed feedback loop: the encoder must reconstruct *exactly what the decoder will
see* (using only quantised data) and predict the next frame from that, or errors drift without bound.
Every stage is a trade-off measured on a rate–distortion curve, so the project is as much a
*measurement* problem as a coding one: does half-/quarter-pel motion pay for itself? B-frames? the
loop filter? RDO? Reel answers each with numbers (Bjøntegaard delta-rate) on reproducible content.

## Architecture
```
 gen ──► .y4m ──► encoder ───────────────► .reel ──► decoder ──► .y4m ──► psnr/ssim
                    │  (closed loop)                      ▲
                    └─ recon == decoder output, bit-exact ┘
 package reel/codec
   y4m.go        YUV4MPEG2 reader/writer (4:2:0)
   gen.go        seeded procedural test-sequence generator (pan, objects, mixed, cut, noise)
   metrics.go    PSNR (per plane + weighted), windowed SSIM, BD-rate
   rangecoder.go adaptive binary range coder (two-rate probability models) + bypass bins
   transform.go  4x4 integer core transform, quantiser/dequantiser (H.264-style scaling)
   frame.go      padded planes, border extension
   intra.go      16x16 / 8x8-chroma intra prediction (DC, V, H, TrueMotion)
   interp.go     quarter-pel luma interpolation (6-tap half-pel + bilinear quarter), 1/8-pel chroma
   syntax.go     ONE symmetric macroblock syntax routine used by both encoder and decoder
   recon.go      prediction + residual reconstruction (shared => bit-exact by construction)
   motion.go     motion search (full / diamond), sub-pel refinement, MV prediction (median)
   encoder.go    GOP structure, mode decision (RDO-ish), residual coding
   decoder.go    parse + reconstruct, reorder output, hardened against corrupt input
   deblock.go    in-loop deblocking filter with boundary-strength derivation
   ratecontrol.go  target-bitrate controller
 cmd/reel        CLI: gen | enc | dec | psnr | info | report | selftest
 report.go       HTML rate-distortion lab (inline SVG, light/dark/phone)
```
Key design decision: the macroblock syntax is written **once** as a function over a `bitIO`
interface (encoder side writes the supplied value, decoder side ignores it and returns the decoded
one), so encoder and decoder cannot disagree about the grammar.

## Feature list
| # | Feature | Tier |
|---|---------|------|
| 1 | **Intra codec**: 4x4 integer DCT + quantiser, 4 intra-16x16/chroma prediction modes, zig-zag, context-adaptive binary range coding of coefficients (significance map / levels), `.reel` container, Y4M I/O | **required** |
| 2 | **Inter prediction**: P-frames with motion estimation (full + diamond search with predictor candidates), quarter-pel luma / eighth-pel chroma motion compensation, median MV prediction, skip mode, 16x16/16x8/8x16/8x8 partitions | **required** |
| 3 | **Closed-loop reconstruction**: decoder output is bit-identical to the encoder's reference frames across arbitrarily long GOPs (no drift); robust decoder that rejects corrupt streams without panicking | **required** |
| 4 | **Measurement lab**: seeded procedural video generator (pan / objects / mixed / scene cut / noise), PSNR + SSIM, `info` per-frame/mode statistics, CLI | **required** |
| 5 | In-loop deblocking filter (bS derivation, alpha/beta/tc0 tables) with on/off flag in the stream | stretch |
| 6 | B-frames (bi-prediction, L0/L1/Bi per partition, reordered coding order, non-reference) | stretch |
| 7 | Rate control to a target bitrate (per-frame QP from a bit-model + buffer feedback) | stretch |
| 8 | RDO mode decision (SSD + λ·bits) and adaptive scene-cut I-frame insertion | stretch |
| 9 | HTML rate–distortion lab: R-D curves per tool configuration, BD-rate table, comparison with ffmpeg/libx264 if present, MV and mode maps | stretch |

Required = 1–4. Stretch = 5–9 (aim: all; at least one guaranteed).

## Verification plan
`verify.sh`: gofmt/vet, unit tests (transform round-trip, range coder, interpolation vs brute-force,
syntax encode/decode symmetry fuzz), encode→decode **bit-exact** equality over every tool combination,
corrupt-stream fuzz (no panics), rate-control accuracy, ffmpeg can read our Y4M output, and a tool
ablation asserting each coding tool lowers bitrate at equal quality on suitable content.
