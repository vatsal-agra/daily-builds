# Cadence

A modular music synthesizer and procedural composer written in **pure Python 3** — zero external dependencies, no NumPy, no `wave` module, no `sounddevice`. Everything from the WAV encoder to the Freeverb reverb to the FFT spectrum analyzer is hand-rolled from first principles.

---

## What it does

Cadence generates full musical compositions as stereo 44.1 kHz 16-bit WAV files and self-contained HTML visualizers. Given a key, style, tempo, and random seed it produces a four-track arrangement (melody, bass, pads, drums) with proper harmony, voice leading, and DSP effects.

---

## Quick start

```bash
cd 2026-06-24-cadence

# Compose an 8-bar pop piece in C major, open the HTML in a browser
python cadence.py compose --key C --style pop --bpm 120 --bars 8 \
    --output pop.wav --html pop.html

# Jazz in A minor
python cadence.py compose --key Am --style jazz --bars 8 --output jazz.wav

# Electronic in G minor (faster, harder)
python cadence.py compose --key Gm --style electronic --bars 8 --output elec.wav

# Ambient in D (slow, pad-heavy, long reverb tail)
python cadence.py compose --key D --style ambient --bars 8 --output ambient.wav

# Synthesize a single note
python cadence.py synth --note A4 --waveform sawtooth --duration 2.0 --output note.wav

# Make an HTML visualizer for an existing WAV
python cadence.py visualize --input note.wav --output note.html

# Full demo — all 4 styles + 6 waveform samples
python cadence.py demo --output-dir demo_output

# Library/DSP info
python cadence.py info
```

Run the demo script for a complete end-to-end showcase:

```bash
bash demo.sh
```

---

## Features shipped

### DSP synthesis engine (`synth/`)

| Module | What's in it |
|--------|-------------|
| `core.py` | `parse_note("A4") → 69`, `note_to_freq(69) → 440.0`, flat names (Bb3, Eb4, …) |
| `oscillator.py` | 7 waveforms: sine, sawtooth, rsaw, square, triangle, pulse, noise — all non-sine with **PolyBLEP antialiasing** |
| `envelope.py` | ADSR via list comprehensions; correctly handles gate closing during attack/decay |
| `filter.py` | 2nd-order biquad IIR: LPF, HPF, BPF, notch (Audio EQ Cookbook); Direct Form II Transposed; block processing for LFO-modulated cutoff |
| `voice.py` | Polyphonic voice rendering: oscillator → ADSR → LFO (pitch/filter/amplitude) → biquad → volume; 5 drum voices (kick, snare, hihat, open hihat, clap) |
| `effects.py` | Delay (circular buffer + LP damping), Freeverb stereo reverb (8 LBCF + 4 allpass × 2 channels), soft-clip distortion, LFO chorus, knee limiter, peak normalizer |
| `fft.py` | Cooley-Tukey iterative FFT, Hanning-windowed magnitude spectrum, log-spaced spectrum bands |
| `wav.py` | RIFF/WAVE encoder/decoder from scratch using `struct` + `array`; round-trip error < 0.0002 |
| `sequencer.py` | 16-step grid sequencer; offline rendering; polyphony; stereo panning; 2-second release tail |
| `composer.py` | 4 styles × 8 scales × chord progressions → melody + bass + pads + drums; deterministic from seed |
| `visualizer.py` | Self-contained HTML: base64 WAV audio player, waveform canvas, FFT spectrum canvas, piano roll canvas |

### Musical styles

| Style | BPM | Harmony | Drums | Effects |
|-------|-----|---------|-------|---------|
| `pop` | 110–130 | I–V–vi–IV | Four-on-the-floor + snare | Reverb + chorus |
| `jazz` | 140–165 | ii–V–I + substitutions | Swing hihat | Reverb + chorus |
| `ambient` | 60–80 | Extended chords, slower motion | Sparse | Heavy reverb |
| `electronic` | 125–145 | Minor/phrygian, ostinato bass | Hard kick + tight snare | Reverb |

### Bugs fixed during adversarial review (Phase 3)

1. **`soft_limit` allowed outputs > 1.0** — formula `threshold + excess/(1+excess)` asymptotes at 1.9 not 1.0; fixed to `threshold + headroom*(1 - 1/(1+excess/headroom))`
2. **`compute_adsr` division by zero at `gate_samples=0`** — fixed with early return
3. **`parse_note` rejected flat names like `Bb3`** — `_FLAT_MAP` keys were mixed-case but input was `.upper()`ed; fixed by uppercasing all map keys

### Bugs fixed during testing (Phase 5)

4. **`compute_adsr` compressed attack so it still reached 1.0 when gate closed early** — now tracks natural attack duration separately so the envelope only rises to `gate_samples/attack_n_natural`
5. **`Delay` buffer was `delay_n+1` samples** — echo arrived one sample late; fixed by using exactly `delay_n` entries

---

## Test suite

84 unit tests covering every module:

```bash
python tests/test_cadence.py
# Ran 84 tests in 4.1s — OK
```

Tests include: parse_note edge cases, PolyBLEP boundary behavior, ADSR monotonicity, biquad IIR stability at extremes (Q=0.01/20, fc=20/22kHz), WAV round-trip accuracy, Parseval theorem for FFT, sequencer polyphony, composer determinism, and CLI integration tests.

---

## Preset files

JSON preset files in `presets/` can be loaded with `cadence synth --preset presets/lead.json`:

- `lead.json` — sawtooth lead with fast attack, moderate release
- `bass.json` — sub-bass sine with long decay
- `pad.json` — detuned sawtooth pad with slow attack
- `drums.json` — drum voice parameter reference

---

## Where a human could take this next

- **Polyphonic MIDI import** — parse a `.mid` file into `Sequence` objects and render it
- **Real-time playback** — pipe the sample buffer to `pyaudio` or `sounddevice` for live play
- **Plugin architecture** — load waveforms and effects from user Python files at runtime
- **More styles** — blues, reggae, drum-and-bass, classical arpeggios
- **Envelope follower / side-chain compression** — ducking pads under the kick
- **Wavetable synthesis** — interpolate between waveforms over note duration
- **Export stems** — write each track as a separate WAV for DAW import
- **WebAssembly port** — the pure-Python DSP maps cleanly to a WASM synthesizer running in the browser
