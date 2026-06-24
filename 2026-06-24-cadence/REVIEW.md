# Cadence — Adversarial Review (Phase 3)

## Summary

Conducted a hostile review targeting correctness bugs, edge-case failures,
mathematical errors, and UX issues. Found 3 real bugs (one with silent data
corruption, one out-of-range clipping bug), all fixed.

---

## Findings

### Bug 1 — `soft_limit` allowed output > 1.0 (FIXED)

**Severity: High** — the limiter was supposed to prevent clipping, but it didn't.

**Root cause**: The compression formula `threshold + excess / (1 + excess)`
has an asymptote at `threshold + 1`, not at `1.0`. For `threshold = 0.9`,
any sample with `|x| > 1.0` would produce an output > 1.0 (e.g., `soft_limit(100.0)
= 1.89`). The limiter silently passed large signals through, corrupting the WAV.

**Fix**: Changed formula to `threshold + headroom * (1 - 1/(1 + excess/headroom))`
where `headroom = 1 - threshold`. This asymptotically approaches exactly 1.0.

**Verification**: `soft_limit([100, -100, 1.5])` → `[0.9999, -0.9999, 0.9857]`,
all within `(-1, 1)`.

---

### Bug 2 — `compute_adsr` division by zero when `gate_samples=0` (FIXED)

**Severity: Medium** — crashed if a track had zero-length events or was called
with empty patterns.

**Root cause**: `attack_n = min(max(..., 1), gate_samples)` with `gate_samples=0`
gives `attack_n = 0`. Then `gate_off = gate_samples / attack_n = 0/0` → `ZeroDivisionError`.

**Fix**: Added an early return for `gate_samples <= 0`, returning a zero-filled
release buffer. Also guarded the division with `max(attack_n, 1)`.

---

### Bug 3 — `parse_note` rejected flat note names like `Bb3` (FIXED)

**Severity: Medium** — note input in the CLI and composer was case-sensitive in
the wrong direction. `_FLAT_MAP` used `'Bb'` but the code upper-cased the
note string first, giving `'BB'` which wasn't in the map.

**Fix**: Changed `_FLAT_MAP` keys to all-uppercase: `'BB'`, `'EB'`, etc.

---

## Things Verified Correct

- **PolyBLEP antialiasing**: Correctly reduces aliasing energy (0.25→0.07 for
  a 15 kHz sawtooth). Near-discontinuity corrections only affect `2*dt` fraction
  of samples (4086/4096 unchanged for 100 Hz).

- **Biquad IIR filter stability**: All filter types (LPF/HPF/BPF/notch) remain
  stable for extreme parameters (Q=0.01, Q=20, fc=20 Hz, fc=22 kHz). No NaN or
  blow-up detected.

- **ADSR envelope**: Attack is monotonically increasing, release is monotonically
  decreasing. Gate-off level correctly computed even when gate closes during
  attack or decay phase.

- **WAV encoder/decoder round-trip**: Max error < 0.00005 (expected from 16-bit
  quantization). Handles single samples, all-zeros, out-of-range clipping,
  file I/O. Rejects non-RIFF files with a clean ValueError.

- **FFT**: Parseval's theorem holds (energy preserved). DC component correct.
  Non-power-of-2 inputs padded correctly. Peak frequency for a 1 kHz test
  tone located within one bin.

- **Composer determinism**: Same seed always produces identical note sequences.
  Different seeds produce different melodies.

- **Sequencer edge cases**: Empty sequences, tracks with no notes, out-of-range
  step indices, and polyphonic overlapping notes all handled correctly.

- **Voice rendering**: Handles 1-sample gate, 10-second notes, extreme MIDI
  pitches (0 and 127), zero-velocity (all silence), all drum kinds.

---

## UX/Polish Issues Noted

- The `compose` command prints BPM to 0 decimal places even when the user
  specified it exactly; this is fine.
- The ambient style generates a 30s piece (slower BPM), which takes ~15s to
  render in Python. A progress indicator would help for long generations.
- The `--bpm` argument accepts floats but BPM is stored as a float internally;
  integer BPMs work fine.

These are not bugs — the quality bar for Phase 4 polish will address them.
