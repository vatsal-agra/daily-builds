# Cadence — PLAN

## Concept

A complete **modular music synthesizer and procedural composer** written from
scratch in pure Python. Cadence takes the listener from silence to a finished
WAV audio file entirely in Python's stdlib, with no audio libraries, no NumPy,
no SciPy, no external dependencies of any kind.

The project covers three interlocking domains:

1. **DSP synthesis** — real waveform oscillators, ADSR envelopes, biquad IIR
   filters, LFO modulation, voice polyphony.
2. **Music composition** — a step sequencer, scale/mode theory, chord
   progressions, procedural melody + bass + drum generation.
3. **Audio I/O & visualization** — from-scratch WAV encoder, Cooley-Tukey FFT,
   self-contained HTML visualizer with embedded audio + waveform + spectrum +
   piano roll.

## Why It's Interesting

Most "audio from scratch" projects render a single sine tone. Cadence builds the
full chain: synthesis → arrangement → mastering → output. Every primitive is
implemented (biquad filters with Audio EQ Cookbook coefficients, PolyBLEP
antialiasing, Freeverb reverb with LBCF+allpass comb networks, pitch-class set
harmony, offline per-note rendering summed into a mix buffer). The result is
real audio that sounds musical, and can be dropped into any media player.

## Architecture

```
cadence.py            CLI entry point (argparse sub-commands)
synth/
  core.py             SAMPLE_RATE, MIDI↔Hz, note parsing, utilities
  oscillator.py       6 waveforms + PolyBLEP antialiasing
  envelope.py         ADSR (list-based, no per-sample loop)
  filter.py           Biquad IIR: LPF/HPF/BPF/notch + coefficient calculators
  voice.py            render_note() → per-note float sample array
  effects.py          Delay, Freeverb reverb, soft-clip distortion, chorus
  sequencer.py        Event scheduler + multi-track offline renderer
  composer.py         Procedural generation: scales, chords, melody, bass, drums
  wav.py              From-scratch WAV encoder/decoder (struct, array, no wave mod)
  fft.py              Cooley-Tukey FFT over complex numbers (cmath)
  visualizer.py       Self-contained HTML (waveform + spectrum + piano roll + audio)
presets/
  bass.json, lead.json, pad.json, drums.json
tests/
  test_cadence.py     Unit + integration + round-trip + musical property tests
demo.sh               Runs the complete demo pipeline
```

## Feature List

### Required (4)

**R1 — Oscillator bank with PolyBLEP antialiasing**
Six waveform types per voice: sine, square, sawtooth, reverse-sawtooth,
triangle, and variable-width pulse. Non-sine waveforms are bandlimited via the
PolyBLEP algorithm (polynomial correction near discontinuities). Includes an
optional detuned second oscillator for thickening.

**R2 — Full synthesis voice: ADSR + biquad filter + LFO modulation**
Each note renders through: (a) ADSR envelope — linear-ramp attack/decay,
sustain level, release from the actual gate-off level; (b) 2nd-order biquad IIR
filter (LPF / HPF / BPF / notch) computed from Audio EQ Cookbook formulas with
resonance Q; (c) an LFO (sine / square / sawtooth) routing to pitch (vibrato),
filter cutoff (wah), or amplitude (tremolo). Voice polyphony: multiple notes on
the same track are rendered independently and summed.

**R3 — Multi-track polyphonic step sequencer**
A step grid (default 16 steps per bar, configurable) where each step carries
note, velocity, and gate length. Multiple named tracks each have their own
preset. The renderer schedules all events and produces a mixed stereo float
buffer. Includes stereo panning per track.

**R4 — From-scratch WAV encoder/decoder + mixing/mastering**
Encodes 44100 Hz 16-bit stereo PCM WAV using Python's `struct` module — no
`wave` stdlib module. Includes: peak-normalize, soft-limit (tanh), stereo
interleave, and a decoder for round-trip verification. Output plays correctly in
all standard media players.

### Stretch (3)

**S1 — Effects chain: delay, Freeverb reverb, distortion, chorus**
- **Delay**: circular buffer echo with feedback and high-frequency damping.
- **Reverb**: Freeverb architecture — 8 parallel lowpass-feedback comb filters
  (LBCF) + 4 series all-pass filters, stereo with a spread offset. Room size,
  damping, and wet/dry are configurable.
- **Distortion**: hyperbolic-tangent soft-clip with drive parameter.
- **Chorus**: LFO-modulated delay line with linear interpolation.

**S2 — Procedural music composer**
Given a key and style (pop / jazz / ambient / electronic), the composer
generates a complete multi-bar piece: chooses a scale, picks a chord
progression, generates a 16th-note melody (scale-constrained, chord-tone
leaning, approach notes, rests), a bass line (root/fifth pattern or walking),
and a 4/4 drum pattern (synthesized kick/snare/hihat, not samples). The seed
makes generation deterministic.

**S3 — Self-contained HTML visualizer**
A single HTML file (no external dependencies) embedding the full WAV audio as
base64 (playable by the HTML5 `<audio>` tag) plus three Canvas panels: (1)
time-domain waveform of the first 4 seconds; (2) FFT magnitude spectrum (10 Hz
to 8000 Hz, log frequency axis, from-scratch Cooley-Tukey FFT with Hanning
window); (3) piano-roll view of all note events on a grid.
