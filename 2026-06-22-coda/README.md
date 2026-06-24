# Coda — MIDI Synthesizer & Procedural Music Generator

A from-scratch MIDI synthesizer and procedural music generation system written
in pure Python 3, zero dependencies. It parses binary MIDI files, synthesizes
audio using real signal-processing, generates complete multi-track pieces using
music theory and Markov chains, and produces a self-contained interactive HTML
piano roll visualizer with Web Audio API playback.

## Quick Start

```bash
# Generate a piece, render to WAV, and open the piano roll in one command:
python3 cli.py make --scale minor --bpm 140 --drums rock --seed 7

# Opens: piece.mid + piece.wav + piece_roll.html
# Open piece_roll.html in a browser → click Play to hear it synthesized in-browser

# Run the full demo (generates 3 styles + effects):
bash demo.sh
```

## All Commands

```
coda generate  [--key KEY] [--scale SCALE] [--bpm BPM] [--bars N]
               [--drums STYLE] [--seed SEED] [--out FILE.mid]

coda render    <file.mid> [--out FILE.wav] [--reverb] [--delay] [--lpf]

coda make      [same as generate + render + viz in one step]

coda viz       <file.mid> [--out FILE.html] [--title TITLE]

coda info      <file.mid>

coda demo      # Generate 4 styles, render, and create visualizers

coda help
```

**Scales:**  `major`, `minor`, `dorian`, `mixolydian`, `pentatonic`, `minor_pent`, `blues`  
**Drums:**   `standard`, `rock`, `jazz`, `electronic`  
**Key:**     note name (`C`, `D#`, `G`) or MIDI number (`60` = C4, `69` = A4)

## Features Shipped

### Required

1. **WAV Synthesis Engine** — Floating-point stereo PCM at 44100 Hz, 16-bit.
   Waveforms: sine (exact), square and sawtooth (band-limited via additive
   synthesis), triangle, white noise. ADSR envelopes with attack, decay,
   sustain level, and release. Polyphonic voice allocator (unlimited voices,
   each rendered independently). Constant-power stereo panning. Auto-normalize
   to −1 dBFS peak.

2. **MIDI Binary Parser** — Reads standard MIDI files (Type 0 and Type 1).
   Variable-length quantity (VLQ) delta-time decoding. Running status. All
   channel-voice messages (Note On/Off, Aftertouch, Control Change, Program
   Change, Channel Pressure, Pitch Bend). All meta events (Tempo Change, Time
   Signature, Key Signature, Track Name, Lyrics, End of Track). Round-trip
   write back to valid MIDI. Handles NoteOn velocity=0 as NoteOff (per spec).

3. **MIDI Renderer (MIDI → WAV)** — Piecewise-linear tempo map supporting
   multiple Tempo Change events. General MIDI program routing (all 128 programs
   mapped to synthesizer presets). Channel 10 drum routing with voice-specific
   ADSR envelopes. Flushes held notes at end of piece. 6 named instrument
   timbres built from additive synthesis + FM: piano, electric piano, organ,
   strings, choir, guitar, bass, brass, flute, marimba.

4. **Procedural Music Generator** — Generates a complete multi-track Type-1
   MIDI file with: (a) key and scale (7 modes); (b) diatonic chord progression
   chosen from a style-appropriate library of Roman-numeral patterns; (c) Markov
   melody with weighted stepwise motion + 40% chord-tone gravitational bias;
   (d) walking bass line on chord roots, fifths, and thirds; (e) 16th-note drum
   pattern (4 styles) with kick, snare, hi-hat, crash, and probabilistic ghost
   notes. Deterministic with `--seed`.

### Stretch

5. **Effects Chain** — Three real DSP effects:
   - **Biquad Low-Pass Filter** — bilinear-transform second-order IIR.
     Configurable cutoff (Hz) and Q factor. Per-channel state.
   - **Schroeder Reverb** — 4 parallel comb filters + 2 allpass filters, each
     with stereo spread. Configurable room size, wet/dry, and damping.
   - **Ping-Pong Delay** — Alternating L/R stereo delay with configurable
     delay time (ms) and feedback. Bounded decay for stability.

6. **Piano Roll HTML Visualizer** — Self-contained single-file HTML (~65 KB):
   - Horizontal piano roll with color-coded tracks (one per MIDI track).
   - Vertical piano keyboard with octave labels.
   - Web Audio API playback: OscillatorNode + GainNode ADSR, drum noise
     buffers, per-track gain, animated playhead with auto-scroll.
   - Mouse hover tooltip: note name, MIDI number, track, channel, velocity.
   - Click anywhere on the roll to seek.
   - Horizontal and vertical zoom sliders.

## Architecture

```
wav.py          — AudioBuffer, WAV file I/O, MIDI note → Hz
synth.py        — Waveforms, ADSR, polyphonic voice renderer
instruments.py  — 10 instrument presets (additive + FM) + GM drum map
midi.py         — Binary MIDI parser + writer (VLQ, running status, all events)
renderer.py     — TempoMap, MIDI → AudioBuffer renderer
generator.py    — Scale/chord theory, Markov melody, bass, drums → MIDI
effects.py      — BiquadLPF, SchroederReverb, PingPongDelay
viz.py          — Self-contained HTML piano roll + Web Audio playback
cli.py          — Main CLI (generate/render/make/viz/info/demo)
tests.py        — 86-test suite
demo.sh         — Full demo script
```

**Stack:** Pure Python 3 stdlib only (no dependencies, no numpy, no scipy,
no mido, no pygame). Generated self-contained HTML/JS/CSS for the visualizer.

## Running Tests

```bash
python3 tests.py
# Ran 86 tests in ~18s — all OK
```

## Why I Built This

All previous builds in this series were either algorithmic/CS (SAT solvers,
databases, compilers, regex engines) or visual (chess, physics, world
generation, typesetting). Nothing had **audio output** — the immediate,
tangible quality of "you can press play and hear what the algorithm made."

Music synthesis also touches a genuinely different stack of interesting problems:

- **Binary format parsing** with variable-length quantities (MIDI's VLQ
  encoding is elegant; running status is a clever space optimization).
- **Signal processing mathematics** — the bilinear transform, biquad filter
  design, Schroeder's reverberator network, additive synthesis harmonics.
- **Music theory as algorithms** — formalizing what musicians describe
  intuitively: scales as integer sets, chord progressions as degree sequences,
  voice leading as distance minimization in scale-degree space.
- **Markov creativity** — a simple transition matrix produces surprisingly
  musical output because the underlying structure (scale adherence, gravity
  toward chord tones) is already in the state space.

## Where a Human Could Take This Next

- **Better instrument models** — wavetable synthesis (record real instrument
  samples + interpolate) for realistic piano, strings, or brass
- **MIDI import from real files** — render actual MIDI compositions from the
  internet through the synth
- **Humanization** — micro-timing offsets and velocity curves to eliminate
  the robotic grid feel
- **Extended harmony** — 7th chords, suspensions, secondary dominants, or
  full jazz chord substitutions
- **Real-time MIDI output** — integrate with the system MIDI bus via `rtmidi`
  to play through a hardware/software synthesizer
- **Machine-learning melody** — train a small RNN or transformer on MIDI
  datasets rather than a hand-coded Markov matrix
- **Audio-to-MIDI transcription** — build a pitch detector (FFT + HPS) and
  feed recorded audio back into the MIDI pipeline
- **Browser-native app** — port the generator and synth to JavaScript (the
  Web Audio API already exists) for an entirely browser-based music-making tool
