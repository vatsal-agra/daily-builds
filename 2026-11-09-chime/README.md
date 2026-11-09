# Chime
A from-scratch perceptual audio codec (MDCT + psychoacoustics + range coding) in Go, stdlib only.

**Status:** Phase 5 (verification) complete — `./verify.sh` is green (unit tests, CLI round trips, perceptual-vs-flat gate, report). Phase 4 (stretch + polish) complete — M/S stereo, noise filling and the HTML report (`chime report`) are shipped. Phase 3 (adversarial review) complete — findings and fixes in [REVIEW.md](REVIEW.md); plan in [PLAN.md](PLAN.md).

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

Phase 3 hardened: non-finite input rejected, M/S noise budget fixed, a pre-echo-aware temporal metric and a
spectral-hole metric added, noise-fill side info cut from 84% to 17% of a starved stream, header layout
fingerprint, hostile-stream fuzzing.

Phase 4: `chime report -b 48 -o r.html in.wav` writes a self-contained, light/dark/phone-friendly report
(spectrograms of original/decoded/error, per-frame switching strips, bit allocation, metrics vs flat baseline).
The flat baseline now dithers its step between bands so equal-bitrate comparisons land within 1%.
