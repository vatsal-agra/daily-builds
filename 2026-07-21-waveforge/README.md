# Waveforge

A from-scratch software synthesizer + step sequencer. Every stage of the
audio signal chain — oscillators, envelopes, a filter, effects, and the
WAV file itself — is built from raw sample-array math, not borrowed from
an audio library or a Web Audio synthesis node. The same `dsp.js` /
`sequencer.js` engine drives both a Node CLI (renders a pattern straight to
a real `.wav` file) and a browser step-sequencer UI.

## What it is

- **Oscillators**: sine, saw, square, triangle, and noise, generated with a
  phase-accumulator (so there's never a click at the wrap point).
- **ADSR envelope + resonant low-pass filter**: shape each note's amplitude
  and timbre. The filter is a real biquad (RBJ cookbook design) with
  cutoff + resonance (Q).
- **Multi-track, polyphonic step sequencer**: any number of tracks, each
  with its own instrument patch, all mixed together; a 16-step grid with
  per-step velocity (off / soft / mid / accent).
- **A hand-written WAV encoder**: 44-byte RIFF/WAVE header plus 16-bit PCM
  samples, written byte-by-byte — no audio codec library involved.
- **Effects**: a feedback delay line and a classic Schroeder reverb
  (4 parallel combs + 2 series allpasses).
- **Patch save/load**: any track's instrument (waveform + envelope +
  filter) serializes to JSON and can be downloaded, edited, and reloaded.
- **7 built-in instrument patches**: kick, snare, hi-hat, bass, lead, pad,
  pluck — including a pitch-drop envelope on the kick for that classic
  "thump" character.

## How to run it

**Browser (interactive sequencer):**
```
cd 2026-07-21-waveforge
python3 -m http.server 8000
# open http://localhost:8000/index.html
```
Click steps to program a beat (click cycles off → soft → mid → accent →
off), tweak each track's waveform/ADSR/filter, hit **Play**, or **Export
WAV** to download the rendered song. **Load demo song** loads a full
6-track example. Delay/reverb toggles live in the FX bar; each track has
its own Save (⇩) / Load (⇧) patch buttons.

**CLI (headless rendering):**
```
node render.js demo-pattern.json out.wav   # renders straight to a real WAV file
```
Any pattern JSON (see `sequencer.js`'s doc comment for the shape) works —
not just the bundled demo.

**Tests:**
```
./demo.sh          # full suite: unit tests + CLI render + browser UI smoke test
node test/run.js   # just the 33 unit tests
```

## Full feature list

**Required (Phase 2):**
1. Multi-waveform oscillator engine (sine/saw/square/triangle/noise, phase-accumulator)
2. ADSR envelope + resonant biquad low-pass filter per voice
3. Multi-track, polyphonic step sequencer (arbitrary track count, mixed additively)
4. Hand-written WAV file export (CLI writes to disk, browser downloads a Blob)

**Stretch (Phase 4):**
5. Effects chain: feedback delay + Schroeder reverb, verified to produce a real audible tail
6. Patch save/load as JSON, with a "Custom (loaded)" indicator in the UI so the preset dropdown never misrepresents the active patch

**Bonus (came along for the ride):**
- Swing timing (per-off-beat micro-delay)
- Pitch-drop envelope on percussive patches (the kick's characteristic downward pitch sweep)
- A soft-knee (tanh) master limiter, so no combination of voices/effects can produce harsh digital clipping

## Why I chose this today

Every past daily build in this repo that touches signal processing or
low-level engines (a 3D rasterizer, a SQL engine, a regex engine, several
constraint solvers, a quantum simulator, a path tracer) — but nothing
audio. Audio synthesis has the same appeal: real DSP math (phase
accumulators, biquad filter coefficients, Schroeder reverb topology) with
an immediately audible, demoable result. The constraint I set myself —
the entire engine has to run identically in Node (no browser APIs at all)
and in a `<script>` tag (no bundler, no Web Audio synthesis nodes) — forced
a cleaner architecture than "just wire up some OscillatorNodes" would have,
and it's what made the whole thing testable with real assertions on
sample data instead of "it sounded okay when I clicked play."

## Where a human could take this next

- **Per-step pitch editing in the UI.** Right now the interactive grid
  edits one base note per track; the engine already supports a distinct
  MIDI note per step (used by the CLI/demo song's bass and lead lines) —
  wiring up a proper piano-roll-style per-step note picker would unlock
  real melodies from the UI, not just rhythm.
- **More waveforms / wavetables.** FM synthesis, or loading a custom
  single-cycle wavetable, would open up a much wider timbral palette
  beyond the 5 basic waveforms.
- **Polyphonic filter modulation (an envelope on the filter, not just
  amplitude)** — classic subtractive-synth "filter envelope" — would add
  a lot of character (a filter that opens on attack and closes on
  release) for relatively little code.
- **Pattern chaining / song arrangement** — right now a "pattern" is one
  bar; a simple sequence-of-patterns concept (verse/chorus-style
  arrangement) would turn this from a "one loop" tool into something closer
  to a real tracker.
  - **Undo/redo and per-track step-length** (some tracks having 8 steps,
  others 32, for polyrhythms) are both natural, contained extensions of
  the existing data model.

## Files

- `dsp.js` — DSP core (oscillators, envelope, filter, effects, WAV codec)
- `sequencer.js` — pattern data model + polyphonic renderer + validation
- `presets.js` — 7 built-in instrument patches
- `render.js` — CLI renderer
- `demo-pattern.json` — 6-track example song
- `index.html` / `app.js` / `style.css` — browser UI
- `test/run.js` — 33-test unit suite
- `test/ui_smoke.mjs` — headless-browser UI smoke test
- `demo.sh` — runs everything above in one shot
- `PLAN.md` — Phase 1 concept/architecture/feature plan
- `REVIEW.md` — Phase 3 adversarial review findings and fixes
