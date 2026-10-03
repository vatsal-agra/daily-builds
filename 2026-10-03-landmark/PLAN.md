# Landmark — PLAN

## Concept
**Landmark** is an audio-fingerprinting engine in the style of Shazam (Wang, 2003, *"An Industrial-Strength
Audio Search Algorithm"*), written from scratch in Go with zero dependencies. Give it a few seconds of
degraded audio — noisy, filtered, distorted, reverberant, even sped up — and it names the song and says
where in the song the clip came from.

Because the repo has no audio corpus (and I will not hand-wave one), Landmark also ships a **procedural
music synthesizer** that composes real multi-instrument songs (chords, bass, melody, drums) from a seed. The
whole pipeline — compose → WAV → resample → STFT → constellation → combinatorial hashes → inverted index →
offset-histogram voting — is real signal processing on real waveforms, and the evaluation harness attacks it
with genuine signal degradations.

## Why it's interesting
* The core trick is beautiful: raw spectrogram peaks (the "constellation map") survive noise because the
  loudest time-frequency peaks stay loudest; pairing peaks into `(f1, f2, Δt)` hashes makes them
  *time-shift invariant*, and a histogram of `songTime − queryTime` turns thousands of weak, noisy hash
  collisions into one unmistakable spike.
* New domain for this repo (no audio-search/DSP-retrieval build yet; Waveforge/Coda synthesize audio, none identify).
* Fully self-verifying: an eval harness measures accuracy vs. SNR, filtering, reverb, clipping, clip length, and
  false-accept rate on songs that are *not* in the index.

## Architecture
```
cmd/landmark        CLI (synth, index, identify, degrade, eval, timeline, viz, info)
internal/wavio      RIFF/WAVE reader (PCM 8/16/24/32, float32, any channels→mono) + 16-bit writer
internal/dsp        radix-2 FFT, Hann STFT, windowed-sinc resampler (arbitrary real ratio), biquad lowpass
internal/synth      seeded procedural composer/renderer (additive lead, pad, bass, kick/snare/hat)
internal/degrade    crop, white/pink noise at target SNR, gain, lowpass, tanh distortion, reverb, speed change
internal/fp         spectrogram → peak picking (separable max filter + density cap) → anchor/target pair hashing
internal/index      inverted index (hash → postings), compact varint file format, offset-vote matcher
internal/eval       robustness benchmark + false-accept test → markdown table
internal/timeline   sliding-window identification → merged segments ("what's playing when" in a DJ mix)
internal/viz        self-contained HTML report: spectrogram, constellation, matched pairs, offset histogram
```
Pipeline: `samples → resample 8 kHz → STFT(1024, hop 256) → dB → peaks → pairs(fan-out) → 24-bit hash`.
Matching: look up each query hash, vote `(song, Δ=tSong−tQuery)`, score = tallest Δ-bin (±1 frame), accept if
above an absolute floor *and* clearly ahead of the runner-up.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | WAV I/O + DSP core (FFT, STFT, windowed-sinc resampler, biquad) | **required** |
| 2 | Constellation extraction + combinatorial hashing (time-shift-invariant landmarks) | **required** |
| 3 | Persistent inverted index + offset-histogram matcher with confidence & reject ("no match") logic | **required** |
| 4 | Procedural song synthesizer + degradation toolkit + robustness/false-accept evaluation harness | **required** |
| 5 | Speed/pitch-tolerant search (scan resample factors, report estimated speed) | stretch |
| 6 | Timeline mode: segment a long DJ-style mix into (song, start, end, offset) | stretch |
| 7 | Self-contained HTML visualizer (spectrogram + constellation + matched pairs + histogram) | stretch |

## Done means
Eval table shows ≥95% accuracy on clean/moderate degradations at 10 s clips, 0 false accepts on unindexed
songs, timeline recovers the true track list of a mix, `go test ./...` green, `demo.sh` runs end-to-end.
