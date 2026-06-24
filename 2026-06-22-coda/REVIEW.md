# Coda — Adversarial Review

## Issues Found and Fixed

### Critical (would produce wrong audio)

**1. Bass notes in wrong octave — FIXED**
- `generate_bass` used `degree_to_midi(root_midi + 36, ...)` which put bass notes
  at MIDI 96-103 (C7-G7) instead of the intended bass register (34-55).
- The filter `28 <= n <= 60` silently passed an empty list, and the fallback
  `[chord_root_midi]` just kept the wrong note.
- Fix: changed `root_midi + 36` to `root_midi - 24`, placing bass 2 octaves
  below the key root (e.g., C4 root → C2 bass). Now bass ranges 34-52.

**2. Chord voicings in wrong octave — FIXED**
- `generate_chords` used `degree_to_midi(root_midi + 48, ...)` which put chords
  at MIDI 108-120 (C8 and above, beyond the 88-key piano range).
- Fix: changed to `degree_to_midi(root_midi, ...)`, placing chords in the
  natural 4th/5th octave (60-77). Now musically appropriate mid-register voicings.

### Moderate (wrong behavior, doesn't crash)

**3. `normalize()` only clipped, never boosted — FIXED**
- The original normalize only called `apply_gain` when `peak > target`, meaning
  quiet mixes (peak=0.099) would never be brought up to a useful listening level.
- Fix: changed condition to `peak > 1e-6`, so audio is always normalized to the
  target level (0.9) unless it's silent. This makes all rendered audio at proper
  volume regardless of how many notes overlap.

**4. `bass_notes_pool` could be empty — FIXED**
- When `bass_notes_pool = [n for n in notes if 28 <= n <= 60]` filtered
  everything out (as happened with the wrong octave), the fallback was added
  (`[chord_root_midi]`) but that just kept the bad note.
- After fixing the octave offset, the fallback is now a genuine safety net for
  unusual configurations. The range was also widened to 28-60 from 28-55 to
  accommodate minor scales with higher chord roots.

**5. `renderer.py` imported `noise_burst` from wrong module — FIXED**
- `from instruments import noise_burst` caused ImportError since `noise_burst`
  lives in `synth.py`.
- Fix: changed import to `from synth import noise_burst`.

### Minor (robustness / UX)

**6. `generate_piece` silently accepted `num_bars=0`**
- Passing `num_bars=0` generated an empty MIDI file without error.
- This is acceptable behavior (produces a valid but empty MIDI file), not a crash.
- Status: documented as acceptable; the CLI validates bars >= 4 so users can't
  trigger it through normal usage.

**7. Scale adherence confirmed correct**
- Melody notes were 0% off-scale, verifying the Markov chain correctly constrains
  itself to the selected scale.

## Items Confirmed Working

- VLQ encoder/decoder: round-trips all values 0 to 268435455 (4-byte max)
- MIDI running status: correctly parsed
- NoteOn velocity=0 correctly treated as NoteOff
- WAV header byte values verified correct (RIFF/WAVE/fmt/data chunks)
- Tempo map: exact tick-to-seconds conversion with multiple tempo changes
- End-of-track meta events: exactly one per track
- Note pairing: zero orphaned NoteOff events, zero unclosed notes
- ADSR shape: attack 0→1, decay 1→sustain, release sustain→0 all verified
- Frequency accuracy: A4 sine wave zero-crossings within 2 of expected
- Schroeder reverb: no instability or clipping (impulse response bounded)
- Ping-pong delay: no clipping (feedback bounded < 1.0)
- Biquad LPF: passes 440 Hz, attenuates 20 kHz correctly
- CLI error handling: all bad inputs exit with code 1 and clear error message
- All 7 scales work without crash, all note ranges musically valid
- Empty MIDI file parses correctly
- Truncated track chunk handled gracefully (partial data parsed)
- Corrupt file (non-MIDI RIFF) raises clear ValueError

## Fresh Run-Through After Fixes

After all fixes:
- Major piece: bass 34-52, chords 60-76, melody 64-81, drums 36-49 ✓
- All 7 scales: bass and chords in correct register ✓
- WAV output: normalized to peak 0.900 ✓
- MIDI round-trip: exact tick preservation ✓
- Effects chain: no clipping ✓
- HTML visualizer: 21KB generated ✓
