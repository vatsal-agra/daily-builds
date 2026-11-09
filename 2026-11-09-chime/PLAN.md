# Chime — PLAN

## Concept
Chime is a from-scratch **perceptual audio codec** (MP3/AAC family) in Go, stdlib only.
Audio goes in as WAV, comes out as a compact `.chm` bitstream, and a decoder turns it back
into WAV. Unlike a plain transform coder it spends bits where the *ear* can hear them: a
psychoacoustic model decides how much quantisation noise each critical band can hide under
masking, and the quantiser steps follow that.

The repo already has an image codec (JPEG-style) and a video codec (Reel) but no audio
codec, no MDCT/TDAC lapped transform, no psychoacoustics. This build adds all three.

## Why it is interesting
* The MDCT is a *critical-sampled lapped* transform: aliasing cancels only between
  overlapping frames (TDAC). Getting window shapes right across block switching is a classic
  place to get subtly wrong output; here it is verified to perfect reconstruction to 1e-9.
* Psychoacoustics is "physics of hearing" turned into code: Bark scale, spreading function,
  tonality-dependent masking offset, absolute threshold of hearing.
* The honest test of a perceptual codec is that it *loses* on SNR and *wins* on
  noise-to-mask ratio at equal bitrate. Chime ships an evaluation harness that proves exactly that
  against a non-perceptual baseline that shares the same transform and entropy coder.

## Architecture
```
 WAV ─► frame planner ─► MDCT (long 2048 / 8×short 256, KBD-free sine windows,
        (transient         start/stop windows for TDAC)
         detector)           │
                             ▼
                 psychoacoustic model  ──► per-band masking threshold
                             │
                 quantiser (step per band, scalefactor = 2^(s/4))
                             ▼   ▲ rate loop: bisect global offset to hit kbps
        adaptive binary range coder, context-modelled
                             ▼
                      .chm container (CRC32)  ─►  decoder  ─► IMDCT+overlap-add ─► WAV
```
Packages: `codec/` (library), `cmd/chime/` (CLI). Modules: wav, fft, mdct, window switching,
bands/Bark, psy, rangecoder, bitstream coder, encoder, decoder, container, metrics, synth, report.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | MDCT/IMDCT (FFT-based DCT-IV) with TDAC perfect reconstruction, sine windows, adaptive **block switching** (long / start / 8×short / stop) driven by a transient detector | **required** |
| 2 | **Psychoacoustic model**: Bark bands, spreading function, tonality (spectral flatness) dependent masking offset, absolute threshold of hearing, pre-echo-aware short-block thresholds | **required** |
| 3 | **Entropy coding + rate control**: context-adaptive binary range coder for band flags / scalefactors / coefficients; `.chm` container with CRC; bisecting rate loop for a target kbps (`-b`) or fixed quality (`-q`); decoder with hostile-input safety | **required** |
| 4 | **Evaluation harness**: WAV I/O, deterministic procedural test-signal generator (tones, castanet-like transients, bells, formant voice, noise, stereo), SNR / segSNR / **NMR** metrics, and a non-perceptual baseline codec compared at equal bitrate | **required** |
| 5 | Adaptive **M/S joint stereo** per frame (bit-cost estimated decision) | stretch |
| 6 | **Noise filling** for bands quantised to zero (coded energy, deterministic PRNG in decoder) | stretch |
| 7 | **HTML report**: embedded spectrograms (original / decoded / error), block-switch strip, per-band bit allocation, metrics table, light + dark | stretch |

Target: features 1–4 solid in Phase 2, 5 and 6 and 7 as time permits (all three intended).
