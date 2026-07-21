# Waveforge — a from-scratch software synthesizer + step sequencer

## Concept

Every audio tool people reach for (a DAW, a synth plugin, `ffmpeg`) hides the
signal chain behind a UI or a codec library. Waveforge builds the whole chain
from first principles instead: oscillators as raw sample-generating math,
envelopes as piecewise gain curves, a filter as a difference equation, effects
as delay-line arithmetic, and a WAV file as 44 bytes of header plus a stream
of 16-bit integers written by hand — no Web Audio synthesis nodes, no audio
codec libraries, no `ffmpeg` shelling out.

## Why this is interesting

- **It's isomorphic.** The entire DSP engine (`dsp.js`) is plain JS with no
  browser APIs, so the exact same code renders a song in Node (for the CLI
  and automated tests) and in the browser (for interactive playback and WAV
  export). That constraint — write audio synthesis that has to work with
  `Math` and `Float32Array` alone, nothing else — is the fun part.
- It touches real DSP: phase accumulators for anti-click oscillators, ADSR
  envelopes, a resonant one-pole/biquad low-pass filter, a delay line, and a
  Schroeder reverb (parallel combs + series allpasses) — the same topology
  used in real reverb units.
- The deliverable is genuinely usable: a step-sequencer UI you can program a
  beat into, hear play, and export as a real `.wav` file that opens in any
  media player.
- It's easy to verify without a human ear: because rendering is pure
  sample-array math, tests can assert on RMS energy, silence, note timing,
  and WAV header bytes — no manual listening required to prove correctness.

## Architecture

```
2026-07-21-waveforge/
  dsp.js         — pure DSP core (no DOM/Web Audio dependency)
                   oscillators, ADSR envelope, biquad LPF, delay, reverb,
                   voice mixer, WAV encoder
  sequencer.js   — pattern data model + render(pattern) -> Float32Array
                   turns a multi-track step pattern into a full song buffer
                   by scheduling voices through the dsp.js engine
  presets.js     — built-in instrument patches (bass, lead, pad, pluck, kick,
                   snare, hat) as plain JSON-serializable objects
  render.js      — Node CLI: `node render.js pattern.json out.wav`
                   renders a pattern file to a real WAV file headlessly
  test/run.js    — Node test harness exercising every feature, asserting on
                   the rendered sample data (RMS, silence, timing, WAV bytes)
  demo-pattern.json — a full example song using every instrument + effect
  index.html / app.js / style.css
                   browser step-sequencer UI: grid editor, per-track synth
                   params, transport (play/stop/loop), WAV export, patch
                   save/load, built-in patch browser
  README.md
```

Data flow: the UI (or the CLI) builds a **pattern** (BPM, steps/beat, and a
list of tracks, each with a patch + a boolean/velocity step grid) →
`sequencer.render(pattern)` walks the grid, and for every active step spawns
a **voice** (oscillator + ADSR + filter) at the right sample offset, sums all
voices into a master buffer, runs the master buffer through the effects
chain (delay, reverb), then hard-limits it → the resulting `Float32Array` is
either fed to an `AudioBuffer` for playback or handed to `encodeWav()` for
a downloadable/writable `.wav` file.

## Features (4 required + 3 stretch)

**Required**
1. **Multi-waveform oscillator engine** — sine, saw, square, triangle,
   noise, with phase-accumulator generation (no clicking at loop points) and
   per-voice pitch (MIDI note → frequency).
2. **ADSR envelope + resonant low-pass filter per voice** — attack/decay/
   sustain/release shapes each note's amplitude; a biquad LPF with cutoff +
   resonance sculpts the timbre, both driven by patch parameters.
3. **Multi-track step sequencer with polyphony** — a grid of tracks × steps,
   each track has its own instrument patch, arbitrary step count/BPM, and
   more than one track can sound at once (polyphonic mixing), demonstrated
   with a full demo song (kick/snare/hat/bass/lead).
4. **From-scratch WAV file export** — a hand-written 44-byte RIFF/WAVE
   header + 16-bit PCM sample writer (`encodeWav`), used both by the Node
   CLI (writes a real `.wav` to disk) and the browser (downloadable file),
   with a round-trip test that re-parses the header of a written file.

**Stretch**
5. **Effects chain: delay + Schroeder reverb** — a feedback delay line and a
   parallel-comb/series-allpass reverb, each toggleable per-song, applied to
   the master bus after mixing.
6. **Patch save/load + built-in patch browser** — patches (oscillator type,
   ADSR, filter settings) serialize to JSON; the UI has a patch browser to
   load one of 7 built-in instruments onto a track, tweak it, and save it
   back out as a downloadable `.json` patch file.
7. *(reserve, only if needed)* Swing/groove timing (per-step micro-timing
   offset) — nice-to-have humanization, lowest priority stretch.

## Testing strategy

Because the DSP core has zero browser dependency, `test/run.js` runs under
plain Node and can render real patterns and assert on the actual sample
data: e.g. a track with all steps off must render silence (RMS ≈ 0), a kick
on beat 1 must have energy concentrated in the first steps, the WAV header
byte layout must match the RIFF spec, filter cutoff sweeps must change
spectral energy, etc. This is real end-to-end verification, not a mock.
