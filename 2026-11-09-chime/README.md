# Chime
A from-scratch perceptual audio codec (MDCT + psychoacoustics + range coding) in Go, stdlib only.

**Status:** Phase 2 (core build) complete. See [PLAN.md](PLAN.md).

Working end-to-end today (`go build ./cmd/chime`):
* MDCT/IMDCT with TDAC perfect reconstruction and adaptive long/short block switching
* Psychoacoustic masking model (Bark bands, spreading, tonality, ATH)
* Context-adaptive range coder, `.chm` container with CRC, bitrate-targeting rate loop
* Evaluation: WAV I/O, procedural test signals, SNR/segSNR/NMR and a flat non-perceptual baseline (`chime eval`)
* Also already in: adaptive M/S stereo, noise filling (`-nf`)

Quick try:
```
chime gen -signal mix -o mix.wav
chime eval -b 48 mix.wav
```
