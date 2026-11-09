# Chime — a from-scratch perceptual audio codec

Chime is an MP3/AAC-family codec written in Go with the standard library only: WAV in, a compact `.chm`
bitstream out, WAV back. It spends bits where the *ear* can hear them — a psychoacoustic model decides how much
quantisation noise each critical band can hide under masking, and the quantiser steps follow that.
~3,600 lines of Go (≈730 of them tests).

## Run it
```bash
cd 2026-11-09-chime
go build -o chime ./cmd/chime

./chime gen -signal mix -seconds 8 -o mix.wav     # procedural stereo test signal
./chime encode -b 64 mix.wav mix.chm              # target 64 kbps (or: -q 20 for fixed quality)
./chime decode mix.chm out.wav
./chime info mix.chm
./chime eval -b 48 mix.wav                        # Chime vs flat baseline, same bitrate
./chime report -b 48 -o report.html mix.wav       # spectrograms + metrics, open in a browser
./verify.sh                                       # everything: vet, tests, CLI round trips, report
```
Signals: `tones castanets bells voice noise sweep silence mix`. Encoder flags: `-b KBPS`, `-q DB`, `-nf` (noise
filling), `-noms`, `-noswitch`, `-flat` (the non-perceptual baseline). Real WAVs (8/16/24/32-bit, float32, mono or
stereo, 8–192 kHz) work too.

## How it works
```
WAV → transient detector → MDCT (2048 long | 8×256 short, start/stop windows) → Bark-band masking model
    → per-band step sizes (2^(s/4)) → adaptive M/S → context-modelled binary range coder → .chm (CRC32)
```
* **MDCT with TDAC**, FFT-based DCT-IV, orthonormal; block switching with proper start/stop windows. Perfect
  reconstruction to 1e‑8 for any long/short pattern (tested).
* **Psychoacoustics**: half-critical-band layout per block size/sample rate, Schroeder spreading, tonality from
  spectral flatness of the MDCT pseudo-spectrum (tone masker −(14.5+z) dB, noise masker −5.5 dB), Terhardt
  absolute threshold, temporal pre-echo limiter.
* **Entropy coding**: one symmetric range-coder code path writes *and* reads the syntax, so encoder and decoder
  cannot drift. Band-zero flags, delta-coded scalefactors, coefficients with neighbourhood contexts (two previous
  coefficients + previous block).
* **Rate control**: bisection of one global dB offset on the *real* entropy-coded size lands within 1% below target.

## Features shipped (all 7)
1. MDCT/TDAC with adaptive long/short block switching *(required)*
2. Psychoacoustic masking model *(required)*
3. Range coder, `.chm` container with CRC and layout fingerprint, bitrate/quality rate loop, hostile-input-safe decoder *(required)*
4. Evaluation harness: WAV I/O, 8 procedural signals, SNR / segSNR / NMR (two resolutions) / spectral-hole metrics, flat baseline at equal bitrate *(required)*
5. Adaptive per-frame M/S stereo with a shared noise budget *(stretch)*
6. Noise filling with grouped levels *(stretch, opt-in `-nf`)*
7. Self-contained HTML report (light/dark/phone) *(stretch)*

## Does it work? (from `chime eval -b 48`, 6 s synthetic clips)
| clip | noise over mask, Chime vs flat | p95 NMR | SNR |
|---|---|---|---|
| mix | 0.15 vs 0.70 dB | +0.7 vs +5.6 | 9 vs 33 dB |
| bells | 0.06 vs 0.55 dB | −2.6 vs +4.4 | 16 vs 38 dB |
| castanets | 0.27 vs 1.25 dB | +1.5 vs +4.0 | 3 vs 29 dB |

At equal bitrate Chime loses badly on SNR and wins on the perceptual measure — exactly what a perceptual codec
should do. Block switching cuts the pre-echo view (256-sample NMR) by ~3× on castanets at 64 kbps.
**Caveat:** the metric shares its masking-model family with the encoder (different spectral estimator), and the
signals are synthetic. It shows the codec does what its model says, not that it sounds good; there are no listening
tests. See [REVIEW.md](REVIEW.md) for the adversarial pass (10 findings, all fixed and regression-tested) and its
honest-limitations list.

## Why this today
The repo has JPEG-style and H.264-style codecs but no audio codec and no lapped transform. It's a compact
project where the interesting failures (TDAC aliasing, pre-echo, a metric that can't see the thing it judges) are
real and checkable, and the result can be *looked at* in a spectrogram.

## Where a human could take this next
* Listening tests / ABX, or implement PEAQ/ViSQOL for a model-independent score; try real music.
* Real CBR with a bit reservoir; per-band RDO quantisation (trellis); short-block grouping to cut scalefactor cost.
* Temporal post-masking, inter-channel masking, intensity stereo, band-limited low-pass decisions, SBR-style HF reconstruction.
* Long-term prediction for strongly tonal material; larger window (4096) for stationary segments; KBD windows.
* Streaming decoder API and a WASM build so the report page could decode in the browser.
