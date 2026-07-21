# Waveforge

A from-scratch software synthesizer + step sequencer. **Status: Phase 5 (verification) complete — build in progress.**

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

## Adversarial review (Phase 3)

Hunted for bugs with hand-crafted malformed inputs and a Playwright
click-through of the UI. Found and fixed 4 real issues — a crash on
`bpm <= 0`, a crash on a patch missing `envelope`, demo-loaded step
velocities not matching the UI's click-cycle levels, and per-step `hold`
(sustain length) silently dropping when a pattern is loaded into the
browser. See [REVIEW.md](./REVIEW.md) for full details, including what was
checked and found *not* to be a bug.

## Stretch + polish (Phase 4)

Both planned stretch features were verified as genuinely working, not just
present:
- **Effects chain (delay + Schroeder reverb):** confirmed a measurable,
  audible difference between the same song rendered with effects on vs.
  off (large sample-level diff, and a real decay tail extending energy
  past where the dry signal goes silent).
- **Patch save/load:** round-tripped a custom patch through Save → Load
  and got back the exact same JSON; confirmed invalid files (non-JSON,
  and valid JSON missing required fields) fail with a clear status
  message instead of crashing.

Additional polish: a hand-inlined SVG favicon (no more 404 in the
console), a "Custom (loaded)" indicator so the preset dropdown never lies
about what patch is actually active, and confirmed graceful behavior for
every "nothing to do" case — 0 tracks, all tracks muted, an out-of-range
BPM typed directly into the input — each shows a clear status message and
never throws.

## Verification (Phase 5)

Run the full suite with `./demo.sh`, or `node test/run.js` for just the
unit tests. Writing the test suite itself turned up two more real bugs,
now fixed:
- The **triangle oscillator was phase-shifted** from the sine/saw/square
  convention — it started at -1 and peaked at phase 0.5, instead of
  starting at 0 (like sine) and peaking at 0.25. Fixed so switching a
  track's waveform never introduces a phase discontinuity at note-on.
- A test asserted an *exact* 0 right at the envelope's release-end
  boundary, where float subtraction leaves a ~1e-16 residual (inaudible;
  16-bit PCM quantizes it away) — loosened the assertion rather than
  chase floating-point noise in production code.

`test/run.js` (33 tests) exercises: every oscillator's actual waveform
shape, ADSR envelope math at each stage, filter attenuation (verified a
real frequency-dependent rolloff, not just "doesn't crash"), WAV header
byte-for-byte correctness, multi-track polyphonic mixing (asserting
combined energy exceeds any single voice), velocity scaling, the delay/
reverb tail, every Phase 3 regression (bad BPM, malformed patch), and the
CLI's exit codes/stderr on bad input. `test/ui_smoke.mjs` drives the real
browser UI end-to-end (add/remove track, step click-cycle, play/stop,
demo load, WAV export) and asserts zero console errors.

More to come as each phase completes.
