# Adversarial review

Findings from attacking Waveforge as a hostile reviewer: hand-crafted
malformed inputs, boundary values, and a full click-through of the browser
UI (via a Playwright smoke session) hunting for crashes, silent wrong
behavior, and rough UX edges.

## Bugs found and fixed

1. **`bpm <= 0` (or `stepsPerBeat <= 0`) crashes with a cryptic engine
   error.** `sequencer.render()` computed `stepDurationSeconds` without
   validating BPM, so a hand-authored `pattern.json` with `"bpm": 0` (or
   negative) produced `Infinity`/`NaN` step durations, which blew up
   `new Float32Array(totalSamples)` with `RangeError: Invalid typed array
   length: Infinity` — a confusing failure for anyone editing a pattern
   file by hand. The browser UI already clamped its BPM input to
   [40, 300], so this was only reachable via the CLI/hand-written JSON, but
   the CLI is a real, documented interface and deserves a real error
   message.
   **Fix:** `sequencer.render()` now validates `bpm > 0` and
   `stepsPerBeat > 0` up front and throws a clear
   `Error('pattern.bpm must be a positive number...')`-style message;
   `render.js` catches it and prints a friendly one-line error to stderr
   with exit code 1, matching the existing JSON-parse-error handling.

2. **A patch missing `envelope` crashes with a low-level property-access
   error.** `dsp.renderVoiceInto` immediately does `patch.envelope.decay`
   etc.; a track patch like `{ waveform: 'sine' }` (no envelope, no filter)
   throws `Cannot read properties of undefined (reading 'release')` deep
   inside the DSP core instead of failing at the boundary with a message
   that names the offending track. The browser's "Load patch…" file input
   already validates `patch.waveform && patch.envelope` before accepting a
   file, so this path was only reachable via a hand-authored pattern.json
   or a track patch loaded some other way — but again, the CLI is a real
   interface.
   **Fix:** `sequencer.render()` now validates every track's patch has a
   `waveform` in the known set and a complete `envelope` (finite
   attack/decay/sustain/release) before rendering, throwing an error that
   names the track (e.g. `Track "Bass": patch.envelope is missing or
   incomplete`). `render.js` surfaces this the same friendly way.

3. **Demo-loaded step velocities don't match the UI's click-cycle
   levels.** The interactive grid cycles a step through 4 discrete
   velocities on click (off → 0.6 → 0.85 → 1.0 → off), but
   `demo-pattern.json` uses finer velocities (0.9, 0.7, 0.8, 0.6) for
   musical dynamics. After "Load demo song", clicking a step whose velocity
   wasn't one of the 4 levels (e.g. 0.9) jumped straight to *off*
   (`indexOf` returns -1, and the code treated "not found" as "currently at
   the last level, wrap to index 0") instead of advancing to the next
   level as every other step does — surprising and inconsistent.
   **Fix:** when the demo song (or any external pattern) is loaded into the
   UI, each step's velocity is now snapped to the nearest of the 4 UI
   levels, so every visible step behaves identically under the click-cycle
   regardless of where it came from.

4. **Per-step `hold` (used by the Pad track to sustain a note across 8
   steps) was silently dropped when a pattern was loaded into the browser
   UI.** `loadDemoSong()` only carried over each step's `velocity` into the
   UI's per-track `steps` array, discarding `hold`. Rendering the demo via
   `node render.js demo-pattern.json out.wav` produces long sustained pad
   notes; pressing "Load demo song" then "Play" in the browser produced
   short, clipped pad notes instead — a real behavioral divergence between
   the two ways of playing the same song, not just a display nicety.
   **Fix:** the UI's per-track step model now carries an optional `hold`
   alongside velocity (as `{ velocity, hold }` when present, otherwise a
   plain number, so the common case stays simple), `buildPattern()` passes
   `hold` through when set, and manually clicking a step to edit it drops
   any inherited `hold` (editing a step means the user now owns its
   timing, which is the least surprising behavior).

## Checked and found not to be bugs

- **Velocity/gain values above 1.0 or below 0** (e.g. a hand-crafted patch
  with `gain: 5` or `velocity: -1`) don't clip cleanly inside
  `renderVoiceInto` itself, but the sequencer's master-bus soft limiter
  (`tanh`) runs over the *entire* summed buffer before WAV encoding, and
  `encodeWav` hard-clamps to `[-1, 1]` as a last-resort safety net — so no
  combination of extreme per-voice values can produce out-of-range or
  clipped-sounding samples in the final output. Verified with a 20-track,
  effects-on stress render: zero non-finite samples, zero samples
  exceeding `[-1, 1]`.
- **Negative envelope `release`** degrades gracefully (the note's
  computed duration shrinks towards zero rather than crashing) rather than
  producing anything audibly broken; not worth a defensive branch for a
  value the UI can't produce (its release slider is `min="0"`).
- **Filter cutoff far above Nyquist / resonance of exactly 0** were both
  already handled by `LowPassFilter.setParams`'s clamps (`cutoffHz` is
  clamped to `[20, sampleRate/2 - 1]`, `Math.max(q, 0.0001)` guards the
  alpha division) — confirmed with direct filter-only tests, no NaNs.
- **`favicon.ico` 404 in the browser console** — cosmetic only (no page
  functionality touches it). Fixed anyway with an inline data-URI favicon
  in Phase 4 polish since it's a one-line fix and cleans up the console.
- **Changing a track's instrument preset mid-edit rebuilds that track's
  whole DOM row**, which drops focus from whatever input was focused. This
  is a minor rough edge, not a crash or data-loss bug (no state is lost,
  only focus), and is an inherent tradeoff of the simple re-render-on-any-
  change architecture used throughout. Not fixed, given the scope of a
  one-day build; noted here rather than silently ignored.
- **Selecting a custom-loaded patch (via "Load patch…") leaves the
  preset `<select>` visually pointing at whatever preset was previously
  selected**, which could read as if the dropdown still reflects the
  active patch. Fixed in Phase 4 polish by adding a synthetic "Custom"
  option that's shown/selected whenever a track's patch didn't come from
  a built-in preset.

## Gate

After the fixes above, the four adversarial scenarios that produced wrong
behavior (bad BPM, malformed patch, mismatched demo velocities, dropped
`hold`) were re-run and all now either behave correctly or fail with a
clear, actionable error message. See `test/run.js` (Phase 5) for the
automated regression coverage of items 1 and 2.
