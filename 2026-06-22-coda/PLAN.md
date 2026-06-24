# Coda — MIDI Synthesizer & Procedural Music Generator

## Concept
Coda is a from-scratch MIDI synthesizer and procedural music generation system
written in pure Python 3, no third-party dependencies. It:

- **Parses** binary MIDI files (Type 0 and Type 1) including all channel
  events and meta events.
- **Synthesizes** audio using real signal-processing: multiple waveforms,
  ADSR envelopes, additive synthesis for instrument timbres, a Schroeder
  reverb, a biquad low-pass filter, and ping-pong delay.
- **Generates** complete procedural music tracks using music theory
  (scales, diatonic chord progressions) and Markov melody chains, writing
  them as valid MIDI files that can be rendered back through the synth.
- **Visualizes** any MIDI file as a self-contained HTML piano roll with
  color-coded tracks, Web Audio API synthesis, and animated playback.

## Why it's interesting

1. **Binary format parsing challenge** — MIDI uses variable-length
   quantities (VLQ) and a two-level event hierarchy (file/track/event)
   that is deceptively simple but full of edge cases.
2. **Signal processing mathematics** — PCM synthesis at 44100 Hz,
   Biquad filter design (bilinear transform), and the Schroeder reverb
   (allpass + comb filter network) are non-trivial to implement correctly.
3. **Music theory as algorithms** — Mapping scales, chord voicings, and
   voice-leading rules into code forces precise formalization of things
   musicians describe intuitively.
4. **Markov chain creativity** — Melody generation is a classic Markov
   application that produces surprisingly musical output with only a few
   states.
5. **Immediate tangibility** — The output is a WAV file you can actually
   listen to and an HTML file you can open in a browser, unlike most
   algorithmic projects whose output is text.

## Architecture

```
2026-06-22-coda/
├── wav.py           — PCM audio buffer + WAV file writer (44100 Hz, 16-bit stereo)
├── synth.py         — Waveforms, ADSR envelope, polyphonic voice allocator
├── instruments.py   — Instrument presets built from additive + FM synthesis
├── effects.py       — Biquad LPF, Schroeder reverb, ping-pong delay
├── midi.py          — Binary MIDI parser (Type 0/1, VLQ, all events)
├── renderer.py      — MIDI → audio: tempo map, channel routing, mix
├── generator.py     — Procedural music: scale, chords, Markov melody, drums
├── viz.py           — Self-contained HTML piano roll with Web Audio playback
├── cli.py           — Main CLI entry point
├── tests.py         — Test suite
├── demo.sh          — Demo script
└── README.md        — Project readme
```

## Features

### Required (4)

1. **WAV Synthesis Engine**
   Floating-point audio buffer with 44100 Hz stereo PCM output written
   as standard 16-bit WAV. Waveforms: sine, square (band-limited via
   additive synthesis), sawtooth, triangle, white noise. ADSR envelopes
   (attack, decay, sustain level, release) with correct phase tracking
   across tick boundaries. Polyphonic voice allocator (up to 32 simultaneous
   voices) with per-voice pitch, velocity, pan, and instrument.

2. **MIDI Binary Parser**
   Reads standard MIDI files (Type 0 and Type 1) from raw bytes. Handles
   variable-length quantity (VLQ) delta-time decoding, running status,
   all channel-voice messages (Note On/Off, Aftertouch, Control Change,
   Program Change, Channel Pressure, Pitch Bend), and all meta events
   (Tempo Change, Time Signature, Key Signature, Track Name, Lyrics,
   End of Track). Exposes a clean event list per track sorted by absolute
   tick.

3. **MIDI Renderer (MIDI → WAV)**
   Reads any MIDI file, builds a tempo map (multiple Tempo Change events
   supported), routes channels to instrument presets (GM program numbers
   mapped to synth instruments), and renders the full mix to a WAV file.
   Channel 10 (drums) is handled separately with noise-based percussion
   sounds. Handles Note Off via both 0x80 status and 0x90 with velocity 0.

4. **Procedural Music Generator**
   Generates a complete 32-bar piece with: (a) a key and mode chosen from
   major, natural minor, dorian, or pentatonic; (b) a diatonic chord
   progression using standard Roman-numeral patterns (e.g., I-IV-V-I,
   i-VI-III-VII); (c) a Markov melody where transition probabilities
   favour stepwise motion and chord tones; (d) a walking bass line following
   chord roots and fifths; (e) a simple but rhythmically correct drum track
   (kick, snare, hi-hat at 16th-note resolution). Writes a valid Type-1
   MIDI file that the renderer can read back.

### Stretch (2+)

5. **Effects Chain**
   Three real DSP effects, each mathematically correct and bypassable:
   - **Biquad Low-Pass Filter** designed via the bilinear transform with
     configurable cutoff (Hz) and Q factor. Applied per-sample on the
     output mix.
   - **Schroeder Reverb** with 4 comb filters + 2 allpass filters in the
     classic Moorer/Schroeder configuration. Room size and wet/dry mix
     configurable.
   - **Ping-Pong Delay** with configurable delay time (ms), feedback, and
     alternating left/right stereo.

6. **Piano Roll HTML Visualizer**
   A self-contained single-file HTML that takes embedded MIDI event data
   (JSON-serialized from the Python parser) and renders:
   - A horizontal piano roll: time on the X axis, pitch on the Y axis,
     notes as colored rectangles (one color per track).
   - A vertical piano keyboard on the left for pitch reference.
   - Web Audio API playback: click Play to hear the piece synthesized in
     the browser using OscillatorNode + GainNode envelopes.
   - Animated playhead that scrolls with the music.
   - Mouse hover shows note name, velocity, and track.
   - Zoom controls (horizontal and vertical).
