# Landmark

**Shazam-style audio fingerprinting, from scratch, in Go (standard library only).** Hand it a few seconds of
degraded audio — noisy, filtered, distorted, reverberant, even sped up — and it names the song and says *where
in the song* the clip came from. It also refuses, with a stated reason, when the audio isn't in its library.

It ships with everything needed to prove that claim without any outside data: a procedural **music synthesizer**
(real chords, bass, melody and drums rendered to WAV), a **degradation toolkit**, a **robustness benchmark**, a
**DJ-mix segmenter** and a self-contained **HTML explainer** of how each query was matched.

```
synth ─► WAV ─► resample 8 kHz ─► STFT ─► peak picking ─► landmark hashes ─► inverted index ─► offset voting ─► verdict
                                         (constellation)  (f1,f2,Δt → 24 bit)  (varint file)   (histogram spike)
```

## Run it

Requires Go ≥ 1.24. No dependencies.

```bash
go build -o landmark ./cmd/landmark

./landmark synth -n 12 -out corpus                         # compose 12 procedural songs (WAV)
./landmark index -out lib.lmk corpus                       # fingerprint them into an index
./landmark degrade -in corpus/song0003.wav -start 20 -len 8 -snr 0 -pink -lowpass 3000 -out q.wav
./landmark identify -db lib.lmk q.wav                      # MATCH song0003 — clip starts at 20.00s
./landmark identify -db lib.lmk -speed 0.06 fast.wav       # also search playback speed ±6 %
./landmark mix -out mix.wav -snr 12 corpus/song0003.wav:5-30 corpus/song0001.wav:20-45 corpus/song0008.wav:0-25
./landmark timeline -db lib.lmk mix.wav                    # which song plays when
./landmark viz -db lib.lmk -out report.html q.wav          # open report.html in a browser
./landmark eval                                            # robustness benchmark (~3 min)
./landmark info -db lib.lmk
```

Exit codes: `0` match, `3` no match (reason printed), `1` error, `2` usage. Real WAVs work too — 8/16/24/32-bit PCM or
float, any channel count (mixed to mono), any sample rate. `./demo.sh` runs 40 assertions through the real CLI;
`go test ./...` runs the unit suites.

## Features

| | Feature | Notes |
|--|---------|-------|
| ✅ required | **WAV I/O + DSP core** | RIFF parser (PCM/float, multi-chunk, truncated-tolerant), radix-2 FFT, Hann STFT, Blackman-windowed-sinc resampler for any real ratio (anti-aliased), RBJ biquad |
| ✅ required | **Constellation + landmark hashing** | Separable O(N) max-filter peak picking (monotonic deque), per-second density cap, anchor→target pairing in a time/frequency zone, 24-bit `f1:9 \| f2:9 \| Δt:6` hash |
| ✅ required | **Persistent index + offset-histogram matcher** | Inverted index, compact varint file with CRC32 + atomic save, `(song, Δ)` voting with ±1-frame tolerance, calibrated accept/reject policy with runner-up, rival-offset and floor tests |
| ✅ required | **Synthesizer + degradations + eval harness** | Seeded composer (scales, progressions, mutating phrases, tuning drift, additive lead/pad/bass, kick/snare/hat); crop, white/pink noise at exact SNR, gain, low-pass, tanh distortion, multi-tap reverb, speed change; 11-condition benchmark with false-accept test |
| ⭐ stretch | **Speed/pitch-tolerant search** | Scans playback-speed factors in parallel, reports the estimated factor, guarded by a *sharpness* test against coincidental matches |
| ⭐ stretch | **Timeline mode** | Sliding-window identification → merged segments with song position; bridges glitches, splits seeks, resolves crossfades mid-fade |
| ⭐ stretch | **HTML visualizer** | Single-file report: spectrogram heat-map, constellation, matched landmarks in green, offset histogram, candidate bars; responsive, dark UI |

## Measured results

From `./landmark eval -songs 40 -trials 30` (reproduce with `-seed 42`):

Corpus: 40 indexed songs × 60 s, 182750 distinct hash keys, 252734 landmarks (105.3 / s of audio). Trials per cell: 30.

| Condition | 5 s clip | 10 s clip |
|---|---|---|
| clean | 100% correct · 0 wrong · offset ✓ 97% | 100% correct · 0 wrong · offset ✓ 100% |
| white noise 10 dB SNR | 100% correct · 0 wrong · offset ✓ 97% | 100% correct · 0 wrong · offset ✓ 100% |
| white noise 0 dB SNR | 97% correct · 0 wrong · offset ✓ 93% | 100% correct · 0 wrong · offset ✓ 97% |
| pink noise -3 dB SNR | 53% correct · 0 wrong · offset ✓ 100% | 100% correct · 0 wrong · offset ✓ 93% |
| low-pass 1.5 kHz | 100% correct · 0 wrong · offset ✓ 97% | 100% correct · 0 wrong · offset ✓ 100% |
| heavy distortion (drive 12) | 50% correct · 0 wrong · offset ✓ 100% | 70% correct · 0 wrong · offset ✓ 100% |
| reverb (wet 0.8) | 97% correct · 0 wrong · offset ✓ 100% | 100% correct · 0 wrong · offset ✓ 100% |
| quiet (-40 dB) + 20 dB SNR noise | 100% correct · 0 wrong · offset ✓ 100% | 100% correct · 0 wrong · offset ✓ 97% |
| phone: lowpass 3 kHz + noise 5 dB + distortion | 53% correct · 0 wrong · offset ✓ 100% | 97% correct · 0 wrong · offset ✓ 100% |
| speed +3% (speed search on) | 100% correct · 0 wrong · offset ✓ 100% | 100% correct · 0 wrong · offset ✓ 100% |
| speed -4% + noise 10 dB (speed search on) | 80% correct · 0 wrong · offset ✓ 92% | 100% correct · 0 wrong · offset ✓ 93% |

False accepts on never-indexed songs: **0 / 80** queries.

Score margin (aligned votes): correct matches p1=21 median=140; never-indexed queries median=8 p99=24 max=24; accept floor=11.

*Offset ✓ = the reported start time was within 0.25 s of the truth (misses are overwhelmingly the second-best of two
equally valid alignments in repeated material — the tool flags those).* The hard rows are the honest operating curve:
a 5-second clip through drive-12 distortion or −3 dB pink noise carries too few surviving landmarks, and the policy
chooses a refusal over a guess — **no condition produced a wrong answer**.

## What I learned building it (the review found real bugs — see REVIEW.md)

* **Test data lies.** My first synthesizer looped every 16 bars, so "wrong offsets" were the matcher *correctly*
  choosing between two identical alignments. Realistic variation fixed the data, not the algorithm.
* **Related songs are the real enemy.** Two songs sharing key and tempo produced 42 aligned votes with no relation
  between them. The fixes — a *rival-offset* test (coincidences make a comb of equal peaks; real matches make one spike)
  and speed *sharpness* (a true time-scale lights up one factor; a coincidence is a plateau across all of them) — came
  from looking at histograms, not from tuning one number.
* **Searching more hypotheses multiplies false positives**, so speed-corrected matches pay a vote penalty plus the
  sharpness test.

## Design choices

* 8 kHz analysis, 1024-point FFT, 256-sample hop (32 ms frames, 7.8 Hz bins). Peaks within a 15×25 (time×freq)
  neighbourhood and 60 dB of the loudest cell; ≤24 peaks/s; fan-out 5 inside a 2 s, ±80-bin zone.
* Everything is deterministic: same seed → same audio → same index bytes.
* Parameters are stored in the index file and validated on load, so a query is always analysed exactly like the library.

## Why I chose this today

The ledger is heavy on engines for *symbolic* problems (SAT, SQL, type inference, CRDTs) and light on *signals*.
Audio fingerprinting is the rare algorithm that is elegant on a whiteboard, brutal to make reliable, and completely
checkable — a clip either lands on the right song at the right second or it doesn't. The synthesizer closes the loop so
the whole product runs offline, and the false-accept problem gave the adversarial-review phase real teeth.

## Where a human could take this next

* **Real recordings.** Point `index` at a folder of real music (WAV), then record a phone clip near a speaker. Expect to
  retune `RangeDB`, `PeaksPerSec` and the policy floor on real spectra; the eval harness takes any corpus with a small
  loader change.
* **Time-stretch without pitch change** (tempo-only), via 2-D scanning or by hashing ratios `Δt₂/Δt₁` and `f₂/f₁`
  (Panako-style) instead of absolute values — removes the speed scan altogether.
* **Scale the index**: sorted on-disk postings + mmap, key-sharding, a daemon with a streaming `identify` socket.
* **Learned landmarks**: replace peak picking with a small CNN embedding for robustness at < 0 dB SNR.
* **Live mode**: feed `timeline` from a microphone ring buffer for continuous "what's playing" tracking.
* **MP3/AAC/FLAC decoding** (only WAV today) and a proper catalogue (artist/title metadata) layered on `Song`.
