# Reel — a from-scratch hybrid video codec (Go)

An H.264-style video codec written in Go with **only the standard library**: encoder, decoder, `.reel` container, procedural
test-video generator, PSNR/SSIM/BD-rate metrics, and an HTML rate–distortion lab. ~5,000 lines incl. tests.
`closed loop → decoder output is bit-identical to the encoder's reconstruction`, verified on every tool combination.

## Run it
```bash
cd 2026-11-08-reel
go build -o reel ./cmd/reel
./reel gen -preset mixed -n 30 -o clip.y4m              # seeded procedural clip (pan|objects|mixed|cut|noise|zoom)
./reel enc -i clip.y4m -o clip.reel -qp 28 -b 2         # B-frames, deblocking, quarter-pel, RDO by default
./reel enc -i clip.y4m -o clip.reel -bitrate 200        # rate control to 200 kbit/s
./reel dec -i clip.reel -o out.y4m                      # any Y4M player / ffmpeg can open it
./reel psnr clip.y4m out.y4m                            # PSNR (Y/U/V/weighted), worst frame, SSIM
./reel info clip.reel                                   # per-frame type, QP, bytes, macroblock mode counts
./reel report -o report.html                            # the lab (≈50 s; -quick ≈ 10 s); a pre-built report.html is checked in
./verify.sh                                             # full gate: build, fmt, vet, tests, CLI, ffmpeg interop, ablation
```
Input is any 8-bit 4:2:0 Y4M (e.g. `ffmpeg -i in.mp4 -pix_fmt yuv420p in.y4m`).

## Features
**Required**
1. **Intra codec** — 4×4 integer core transform + H.264-style quantiser, DC/V/H/TrueMotion 16×16 (luma) and 8×8 (chroma) prediction, zig-zag, context-adaptive binary range coder (significance map, last flag, level binarisation, adaptive two-rate models), Y4M I/O.
2. **Inter prediction** — P-frames; diamond (with predictor candidates) or exhaustive motion search; quarter-pel luma (6-tap half-pel + bilinear quarter) and eighth-pel chroma compensation; median MV prediction; skip mode; 16×16 / 16×8 / 8×16 / 8×8 partitions.
3. **Closed loop** — encoder and decoder share one macroblock-syntax routine (`bitIO` interface) and one reconstruction routine, so they cannot disagree; no drift over any GOP. Decoder is hardened: CRC per frame, bounds on everything, 3,000-stream mutation fuzz with zero panics.
4. **Measurement lab** — seeded generator, PSNR + SSIM + Bjøntegaard delta-rate, `info` statistics, CLI.

**Stretch (all shipped)**: in-loop deblocking filter with boundary-strength derivation; B-frames (L0/L1/bi per partition, reordered coding order); bitrate rate control (remaining-budget model, ±1–5%); RDO mode decision (SSD + λ·bits, residual-drop per 8×8) and motion-compensated scene-cut detection; the HTML lab (`reel report`) with R-D curves, BD-rate ladder, libx264 comparison via ffmpeg, search-algorithm table, per-frame size timeline, MV/mode maps, rate-control accuracy.

## What the lab says (checked-in `report.html`, 176×144, 30 frames, QP sweep 22–38)
| Step (cumulative) | clip `mixed` Δrate vs previous | clip `objects` |
|---|---|---|
| P-frames, 16×16, integer-pel (vs intra-only) | −52.3% | −51.4% |
| + quarter-pel motion | −23.3% | −19.5% |
| + partitions & RDO | −18.0% | −24.8% |
| + deblocking | −5.5% | −6.0% |
| + 2 B-frames | −3.1% | **+3.4%** (B-frames hurt on this clip — reported, not hidden) |
| **all tools vs intra-only** | **−72.8%** | **−71.3%** |
| **all tools vs libx264 medium** | **+33% bits** | **+27% bits** |

Diamond search costs ~4% of full search's SAD evaluations (307 K vs 8.4 M) for ~2% more bits. Rate control lands within 1–5% of targets.
Being ~30% behind a decade-optimised encoder with a day's work is the expected, honest gap (see limitations).

## Layout
`codec/` — `rangecoder.go` `transform.go` `intra.go` `interp.go` `syntax.go` (one symmetric MB grammar) `recon.go` `motion.go` `encoder.go` `deblock.go` `ratecontrol.go` `stream.go` (container + decoder) `gen.go` `metrics.go` `y4m.go`; `cmd/reel/` CLI + report. `PLAN.md`, `REVIEW.md` document the process.

## Why this today
The repo had stills (JPEG), audio, PDFs, compilers — but nothing that exploits **time**. A video codec is a closed feedback loop plus a pile of measurable trade-offs, so it rewards both careful engineering (bit-exactness, robustness) and honest measurement (the lab). Adversarial review earned its keep: a naive scene-cut detector coded a fast scroll as 30 I-frames (504 KB vs 30 KB) until I tested on ffmpeg-generated clips.

## Known limitations
No I4×4 / luma-DC transform, one reference per list, median MV prediction for all shapes, no temporal-direct/weighted prediction, no neighbour contexts for MVD, whole clip in memory, tiny (<10 frame) clips can overshoot a bitrate target. 4:2:0 8-bit only.

## Where a human could take this next
- Intra 4×4 modes + luma DC Hadamard, 8×8 transform, CABAC-style neighbour contexts, trellis quantisation (closest to the x264 gap).
- Multiple references, long-term refs, weighted prediction, hierarchical-B / adaptive B placement, temporal direct.
- Two-pass / VBV-constrained rate control; adaptive quantisation (per-MB QP) with psy-RD.
- Multi-threaded slices, a streaming API, and a tiny WASM player so `.reel` files play in a browser.
- A perceptual metric (VMAF-style) in the lab instead of PSNR/SSIM only.
