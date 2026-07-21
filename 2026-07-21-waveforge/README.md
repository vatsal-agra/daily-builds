# Waveforge

A from-scratch software synthesizer + step sequencer. **Status: Phase 2 (core build) complete — build in progress.**

See [PLAN.md](./PLAN.md) for the full concept, architecture, and feature list.

## Working so far

- `dsp.js` — oscillators (sine/saw/square/triangle/noise), ADSR envelope,
  resonant biquad low-pass filter, delay + Schroeder reverb effects, a
  hand-written WAV encoder/decoder. Zero browser dependency — runs in Node
  and the browser unmodified.
- `sequencer.js` — multi-track, polyphonic step-pattern renderer.
- `presets.js` — 7 built-in instrument patches (kick, snare, hat, bass, lead,
  pad, pluck).
- `render.js` — CLI: `node render.js pattern.json out.wav` renders a pattern
  straight to a real, playable WAV file.
- `index.html` / `app.js` / `style.css` — interactive browser step
  sequencer: add/remove tracks, program a 16-step grid with 3 velocity
  levels per step, tweak each track's waveform/ADSR/filter, play in-browser,
  export to WAV, load/save patches as JSON, load a full demo song.
- `demo-pattern.json` — a 6-track demo song (kick/snare/hat/bass/lead/pad)
  exercising every instrument and both effects.

Verified end-to-end: `node render.js demo-pattern.json demo-output.wav`
produces a real WAV file (correct RIFF header, no NaNs, no clipping); the
browser UI was smoke-tested with Playwright (add/remove track, step
toggling, play/stop, demo load, WAV export/download) with zero console
errors.

More to come as each phase completes.
