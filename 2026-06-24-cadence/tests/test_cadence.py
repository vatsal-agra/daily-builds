#!/usr/bin/env python3
"""Cadence test suite.

Covers:
  - Note/MIDI utilities (core.py)
  - Oscillator waveforms and PolyBLEP antialiasing (oscillator.py)
  - ADSR envelope (envelope.py)
  - Biquad IIR filter (filter.py)
  - Full voice rendering (voice.py)
  - Effects: delay, reverb, distortion, chorus (effects.py)
  - WAV encoder/decoder round-trip (wav.py)
  - FFT correctness (fft.py)
  - Step sequencer (sequencer.py)
  - Procedural composer (composer.py)
  - CLI integration tests (cadence.py)
"""

import math
import os
import sys
import random
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from synth.core import parse_note, note_to_freq, midi_to_name
from synth.oscillator import (
    generate, accumulate_phases, gen_sine, gen_sawtooth, gen_square,
    gen_triangle, gen_pulse, _poly_blep,
)
from synth.envelope import compute_adsr, apply_env
from synth.filter import (
    lpf_coeffs, hpf_coeffs, bpf_coeffs, notch_coeffs,
    apply_filter, apply_filter_block,
)
from synth.voice import render_note, render_drum
from synth.effects import (
    Delay, Reverb, Chorus, soft_clip, soft_limit, normalize_peak,
)
from synth.wav import encode, decode, save as wav_save, load as wav_load
from synth.fft import fft, magnitude_spectrum, spectrum_bands
from synth.sequencer import Sequence, Track, NoteEvent, render
from synth.composer import compose, STYLES, SCALES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rms(samples):
    return math.sqrt(sum(s ** 2 for s in samples) / len(samples)) if samples else 0.0


def _peak(samples):
    return max(abs(s) for s in samples) if samples else 0.0


class TestCore(unittest.TestCase):
    def test_parse_note_standard(self):
        self.assertEqual(parse_note('A4'), 69)
        self.assertEqual(parse_note('C4'), 60)
        self.assertEqual(parse_note('C0'), 12)

    def test_parse_note_sharps(self):
        self.assertEqual(parse_note('C#4'), 61)
        self.assertEqual(parse_note('G#5'), 80)
        self.assertEqual(parse_note('F#3'), 54)

    def test_parse_note_flats(self):
        self.assertEqual(parse_note('Bb3'), 58)
        self.assertEqual(parse_note('Eb4'), 63)
        self.assertEqual(parse_note('Ab5'), 80)

    def test_parse_note_extremes(self):
        self.assertEqual(parse_note('C-1'), 0)
        self.assertEqual(parse_note('B8'), 119)

    def test_parse_note_invalid(self):
        with self.assertRaises(ValueError):
            parse_note('X4')
        with self.assertRaises((ValueError, IndexError)):
            parse_note('A')

    def test_note_to_freq_a4(self):
        self.assertAlmostEqual(note_to_freq(69), 440.0, places=6)

    def test_note_to_freq_c4(self):
        self.assertAlmostEqual(note_to_freq(60), 261.6256, places=3)

    def test_note_to_freq_octave_doubling(self):
        """Frequency should double every octave."""
        for midi in [48, 60, 72, 84]:
            self.assertAlmostEqual(note_to_freq(midi + 12), note_to_freq(midi) * 2,
                                   places=6)

    def test_midi_to_name(self):
        self.assertEqual(midi_to_name(69), 'A4')
        self.assertEqual(midi_to_name(60), 'C4')


class TestOscillator(unittest.TestCase):
    SR = 44100
    FREQ = 440.0

    def _phases(self, n=1024):
        phases, _ = accumulate_phases(0.0, self.FREQ, self.SR, n)
        return phases

    def test_sine_peak(self):
        phases = self._phases()
        samples = gen_sine(phases)
        self.assertAlmostEqual(_peak(samples), 1.0, places=4)

    def test_sine_average_zero(self):
        phases = self._phases(4096)
        samples = gen_sine(phases)
        self.assertAlmostEqual(abs(sum(samples) / len(samples)), 0.0, places=2)

    def test_sawtooth_average_zero(self):
        phases = self._phases(4096)
        dt = self.FREQ / self.SR
        samples = gen_sawtooth(phases, dt)
        self.assertLess(abs(sum(samples) / len(samples)), 0.05)

    def test_square_average_zero(self):
        # Use enough samples for many complete cycles to average out
        phases = self._phases(44100)
        dt = self.FREQ / self.SR
        samples = gen_square(phases, dt)
        self.assertAlmostEqual(sum(samples) / len(samples), 0.0, places=2)

    def test_triangle_rms(self):
        """Triangle RMS should be 1/sqrt(3) ≈ 0.5774."""
        phases = self._phases(44100)  # full second
        samples = gen_triangle(phases)
        self.assertAlmostEqual(_rms(samples), 1.0 / math.sqrt(3), places=2)

    def test_pulse_half_equals_square(self):
        phases = self._phases(2048)
        dt = self.FREQ / self.SR
        sq = gen_square(phases, dt)
        pu = gen_pulse(phases, dt, pw=0.5)
        diffs = [abs(pu[i] - sq[i]) for i in range(len(sq))]
        self.assertLess(max(diffs), 1e-9)

    def test_poly_blep_zero_outside_window(self):
        dt = 0.01
        self.assertEqual(_poly_blep(0.5, dt), 0.0)
        self.assertEqual(_poly_blep(0.3, dt), 0.0)

    def test_poly_blep_nonzero_near_boundaries(self):
        dt = 0.01
        self.assertNotEqual(_poly_blep(0.005, dt), 0.0)
        self.assertNotEqual(_poly_blep(0.995, dt), 0.0)

    def test_all_waveforms_finite(self):
        phases, _ = accumulate_phases(0.0, 15000.0, self.SR, 4096)
        dt = 15000.0 / self.SR
        rng = random.Random(0)
        for wf in ['sine', 'sawtooth', 'rsaw', 'square', 'triangle', 'pulse', 'noise']:
            samples = generate(wf, phases, dt, 0.5, rng)
            self.assertTrue(all(math.isfinite(s) for s in samples),
                            f'{wf} produced non-finite sample')


class TestEnvelope(unittest.TestCase):
    SR = 44100

    def test_peak_reaches_one(self):
        env = compute_adsr(44100, 4410, 0.1, 0.2, 0.7, 0.1, self.SR)
        self.assertAlmostEqual(max(env), 1.0, places=3)

    def test_sustain_level(self):
        attack_n = int(0.05 * self.SR)
        decay_n = int(0.1 * self.SR)
        env = compute_adsr(44100, 4410, 0.05, 0.1, 0.65, 0.1, self.SR)
        sustain_start = attack_n + decay_n + 100
        sustain_end = 44100 - 100
        for i in range(sustain_start, sustain_end, 100):
            if i < len(env):
                self.assertAlmostEqual(env[i], 0.65, places=2)

    def test_release_decreases_to_zero(self):
        env = compute_adsr(4410, 4410, 0.01, 0.05, 0.7, 0.1, self.SR)
        self.assertAlmostEqual(env[-1], 0.0, places=3)

    def test_attack_monotonic(self):
        env = compute_adsr(44100, 4410, 0.2, 0.1, 0.7, 0.1, self.SR)
        attack_n = int(0.2 * self.SR)
        for i in range(attack_n - 1):
            self.assertLessEqual(env[i], env[i + 1] + 1e-9)

    def test_zero_gate(self):
        env = compute_adsr(0, 4410, 0.01, 0.1, 0.7, 0.1, self.SR)
        self.assertTrue(all(abs(s) < 1e-9 for s in env))

    def test_short_gate_during_attack(self):
        # Gate closes before attack completes — no crash, gate_off level < 1
        env = compute_adsr(100, 4410, 1.0, 0.5, 0.7, 0.1, self.SR)
        self.assertLess(max(env), 1.0)

    def test_length_correct(self):
        gate = 22050
        rel_s = 0.2
        env = compute_adsr(gate, int(rel_s * self.SR), 0.01, 0.1, 0.7, rel_s, self.SR)
        expected = gate + int(rel_s * self.SR)
        self.assertEqual(len(env), expected)

    def test_apply_env(self):
        samples = [1.0] * 100
        env = [0.5] * 100
        out = apply_env(samples, env)
        self.assertTrue(all(abs(s - 0.5) < 1e-9 for s in out))


class TestFilter(unittest.TestCase):
    SR = 44100

    def _impulse(self, n=1000):
        return [1.0] + [0.0] * (n - 1)

    def test_lpf_passes_dc(self):
        """DC component should pass through an LPF (unity gain at 0 Hz)."""
        b0, b1, b2, a1, a2 = lpf_coeffs(1000.0, 1.0, self.SR)
        # Drive to steady state with a DC signal
        dc = [1.0] * 2000
        out, _ = apply_filter(dc, b0, b1, b2, a1, a2)
        self.assertAlmostEqual(out[-1], 1.0, places=2)

    def test_hpf_rejects_dc(self):
        """DC should be rejected by HPF (near 0 at 0 Hz)."""
        b0, b1, b2, a1, a2 = hpf_coeffs(1000.0, 1.0, self.SR)
        dc = [1.0] * 5000
        out, _ = apply_filter(dc, b0, b1, b2, a1, a2)
        self.assertAlmostEqual(out[-1], 0.0, places=2)

    def test_lpf_attenuates_high_freq(self):
        """A 10kHz sine should be attenuated by a 1kHz LPF."""
        b0, b1, b2, a1, a2 = lpf_coeffs(1000.0, 0.707, self.SR)
        n = 4000
        high = [math.sin(2 * math.pi * 10000 * i / self.SR) for i in range(n)]
        out, _ = apply_filter(high, b0, b1, b2, a1, a2)
        rms_high = _rms(out[1000:])  # skip transient
        self.assertLess(rms_high, 0.05)

    def test_filter_state_continuation(self):
        """Filter state should persist across calls."""
        b0, b1, b2, a1, a2 = lpf_coeffs(2000.0, 1.0, self.SR)
        sig = [math.sin(2 * math.pi * 440 * i / self.SR) for i in range(100)]
        out_one, _ = apply_filter(sig * 2, b0, b1, b2, a1, a2)
        out_a, state = apply_filter(sig, b0, b1, b2, a1, a2)
        out_b, _ = apply_filter(sig, b0, b1, b2, a1, a2, state)
        combined = out_a + out_b
        diffs = [abs(combined[i] - out_one[i]) for i in range(len(combined))]
        self.assertLess(max(diffs), 1e-10)

    def test_all_filters_stable(self):
        """All filter types should produce finite output for extreme parameters."""
        for ftype, fc, q in [
            ('lpf', 20.0, 0.1), ('lpf', 22000.0, 10.0),
            ('hpf', 100.0, 0.5), ('bpf', 1000.0, 20.0),
            ('notch', 5000.0, 5.0),
        ]:
            out, _ = apply_filter_block(self._impulse(), ftype, fc, q, self.SR)
            self.assertTrue(all(math.isfinite(s) for s in out),
                            f'{ftype}(fc={fc}, Q={q}) produced non-finite output')


class TestVoice(unittest.TestCase):
    SR = 44100

    def _preset(self, **kwargs):
        p = {
            'oscillator': 'sawtooth', 'filter_type': 'lpf',
            'cutoff': 4000.0, 'resonance': 1.5,
            'attack': 0.01, 'decay': 0.1, 'sustain': 0.7, 'release': 0.1,
            'volume': 0.8,
        }
        p.update(kwargs)
        return p

    def test_basic_note(self):
        p = self._preset()
        s = render_note(p, 69, 100, 22050)
        self.assertGreater(len(s), 0)
        self.assertGreater(_peak(s), 0.01)
        self.assertTrue(all(math.isfinite(x) for x in s))

    def test_all_waveforms(self):
        rng = random.Random(0)
        for wf in ['sine', 'sawtooth', 'rsaw', 'square', 'triangle', 'pulse', 'noise']:
            p = self._preset(oscillator=wf, filter_type='none')
            s = render_note(p, 60, 100, 4410, rng)
            self.assertGreater(_peak(s), 0.001, f'{wf} produced near-silence')
            self.assertTrue(all(math.isfinite(x) for x in s), f'{wf} non-finite')

    def test_velocity_zero_is_silence(self):
        p = self._preset()
        s = render_note(p, 69, 0, 22050)
        self.assertAlmostEqual(_peak(s), 0.0, places=10)

    def test_velocity_scales_amplitude(self):
        s_full = render_note(self._preset(), 69, 127, 22050)
        s_half = render_note(self._preset(), 69, 64, 22050)
        ratio = _peak(s_half) / _peak(s_full)
        self.assertAlmostEqual(ratio, 64 / 127, delta=0.05)

    def test_extreme_pitches(self):
        rng = random.Random(0)
        p = self._preset(filter_type='none')
        for midi in [0, 12, 60, 108, 127]:
            s = render_note(p, midi, 80, 4410, rng)
            self.assertTrue(all(math.isfinite(x) for x in s), f'MIDI {midi} non-finite')

    def test_zero_gate(self):
        s = render_note(self._preset(), 69, 100, 0)
        self.assertTrue(all(math.isfinite(x) for x in s))

    def test_lfo_pitch_modulation(self):
        """Pitch LFO should produce different output from a non-modulated voice."""
        p_no_lfo = self._preset(filter_type='none', lfo_depth=0.0)
        p_lfo = self._preset(filter_type='none', lfo_depth=2.0, lfo_target='pitch')
        rng = random.Random(0)
        s1 = render_note(p_no_lfo, 69, 100, 22050, rng)
        s2 = render_note(p_lfo, 69, 100, 22050, rng)
        diff = max(abs(s1[i] - s2[i]) for i in range(min(len(s1), len(s2))))
        self.assertGreater(diff, 0.01)

    def test_drum_kicks(self):
        rng = random.Random(0)
        for kind in ['kick', 'snare', 'hihat', 'open_hihat', 'clap']:
            d = render_drum(kind, 100, rng=rng)
            self.assertGreater(len(d), 0)
            self.assertGreater(_peak(d), 0.001)
            self.assertTrue(all(math.isfinite(s) for s in d), f'{kind} non-finite')

    def test_drum_velocity_scales(self):
        rng = random.Random(0)
        d_loud = render_drum('kick', 127, rng=rng)
        d_soft = render_drum('kick', 50, rng=rng)
        self.assertGreater(_peak(d_loud), _peak(d_soft))


class TestEffects(unittest.TestCase):
    def _tone(self, f=440.0, n=44100):
        return [math.sin(2 * math.pi * f * i / 44100) for i in range(n)]

    def test_delay_produces_echo(self):
        delay = Delay(delay_s=0.25, feedback=0.5)
        signal = [1.0 if i < 10 else 0.0 for i in range(44100)]
        out = delay.process(signal)
        delay_n = int(0.25 * 44100)
        # Echo should appear at delay_n samples after the impulse
        echo_region = out[delay_n:delay_n + 100]
        self.assertGreater(max(abs(s) for s in echo_region), 0.1)

    def test_delay_decays(self):
        """With feedback < 1, successive echoes must decrease."""
        delay = Delay(delay_s=0.1, feedback=0.5)
        impulse = [1.0] + [0.0] * 88200
        out = delay.process(impulse)
        d = int(0.1 * 44100)
        echo1 = abs(out[d])
        echo2 = abs(out[d * 2])
        self.assertGreater(echo1, echo2)

    def test_reverb_stereo_spread(self):
        """Reverb should produce different L and R outputs."""
        rev = Reverb(room_size=0.8, damping=0.5, wet=0.6, dry=0.4)
        impulse = [1.0] + [0.0] * 44099
        l, r = rev.process_mono_to_stereo(impulse)
        self.assertGreater(max(abs(l[i] - r[i]) for i in range(len(l))), 0.001)

    def test_reverb_finite(self):
        rev = Reverb()
        signal = self._tone()
        l, r = rev.process_mono_to_stereo(signal)
        self.assertTrue(all(math.isfinite(s) for s in l + r))

    def test_soft_clip_in_range(self):
        for inp in [0.0, 0.5, 1.0, 1.5, 2.0, 100.0, -100.0]:
            out = soft_clip([inp], drive=3.0)[0]
            self.assertGreaterEqual(out, -1.0)
            self.assertLessEqual(out, 1.0)

    def test_soft_clip_unity_at_zero(self):
        self.assertAlmostEqual(soft_clip([0.0], drive=2.0)[0], 0.0)

    def test_soft_limit_in_range(self):
        for v in [2.0, -2.0, 100.0, 0.5, -0.89]:
            out = soft_limit([v])[0]
            self.assertGreaterEqual(out, -1.0)
            self.assertLessEqual(out, 1.0)

    def test_soft_limit_identity_below_threshold(self):
        self.assertAlmostEqual(soft_limit([0.5])[0], 0.5)
        self.assertAlmostEqual(soft_limit([0.0])[0], 0.0)

    def test_chorus_length_preserved(self):
        ch = Chorus()
        signal = self._tone(n=22050)
        out = ch.process(signal)
        self.assertEqual(len(out), len(signal))

    def test_chorus_modifies_signal(self):
        ch = Chorus(rate=1.0, depth=0.005)
        signal = self._tone()
        out = ch.process(signal)
        diff = max(abs(out[i] - signal[i]) for i in range(len(signal)))
        self.assertGreater(diff, 0.001)

    def test_normalize_peak(self):
        l = [2.0, -1.0, 0.5]
        r = [0.3, -0.5, 1.5]
        nl, nr = normalize_peak(l, r, target=0.88)
        self.assertAlmostEqual(max(abs(s) for s in nl + nr), 0.88, places=6)

    def test_normalize_all_zeros(self):
        l = [0.0] * 100
        r = [0.0] * 100
        nl, nr = normalize_peak(l, r)
        self.assertTrue(all(s == 0.0 for s in nl + nr))


class TestWAV(unittest.TestCase):
    SR = 44100

    def _stereo(self, n=44100):
        l = [math.sin(2 * math.pi * 440 * i / self.SR) * 0.5 for i in range(n)]
        r = [math.sin(2 * math.pi * 880 * i / self.SR) * 0.5 for i in range(n)]
        return l, r

    def test_riff_header(self):
        l, r = self._stereo(100)
        wav = encode(l, r)
        self.assertEqual(wav[:4], b'RIFF')
        self.assertEqual(wav[8:12], b'WAVE')
        self.assertEqual(wav[12:16], b'fmt ')

    def test_size_calculation(self):
        n = 44100
        l, r = self._stereo(n)
        wav = encode(l, r)
        expected_data = n * 2 * 2  # n samples * 2 channels * 2 bytes
        self.assertEqual(len(wav), 44 + expected_data)

    def test_round_trip_accuracy(self):
        l, r = self._stereo()
        wav = encode(l, r)
        l2, r2, sr = decode(wav)
        self.assertEqual(len(l2), len(l))
        self.assertEqual(sr, self.SR)
        max_err_l = max(abs(l2[i] - l[i]) for i in range(len(l)))
        max_err_r = max(abs(r2[i] - r[i]) for i in range(len(r)))
        self.assertLess(max_err_l, 0.0002)  # 16-bit quantisation
        self.assertLess(max_err_r, 0.0002)

    def test_clipping_clamped(self):
        l = [2.0, -2.0, 1.0]
        r = [0.0, 0.0, 0.0]
        wav = encode(l, r)
        l2, r2, _ = decode(wav)
        for s in l2:
            self.assertGreaterEqual(s, -1.0)
            self.assertLessEqual(s, 1.0)

    def test_mismatched_lengths_raises(self):
        with self.assertRaises(AssertionError):
            encode([0.5, 0.5], [0.5])

    def test_bad_magic_raises(self):
        with self.assertRaises(ValueError):
            decode(b'FAIL' + b'\x00' * 40)

    def test_file_roundtrip(self):
        l, r = self._stereo()
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            path = f.name
        try:
            wav_save(path, l, r)
            l2, r2, sr = wav_load(path)
            self.assertEqual(len(l2), len(l))
            self.assertEqual(sr, self.SR)
        finally:
            os.unlink(path)


class TestFFT(unittest.TestCase):
    SR = 44100

    def test_dc_component(self):
        n = 64
        spec = fft([1.0] * n)
        self.assertAlmostEqual(abs(spec[0]), n, places=6)

    def test_single_frequency(self):
        n = 4096
        k = 10  # 10-th harmonic
        signal = [math.cos(2 * math.pi * k * i / n) for i in range(n)]
        spec = fft(signal)
        mags = [abs(x) for x in spec]
        peak_k = mags.index(max(mags))
        self.assertIn(peak_k, [k, n - k])

    def test_parseval(self):
        n = 256
        signal = [math.sin(2 * math.pi * 5 * i / n) + 0.5 for i in range(n)]
        spec = fft(signal)
        e_time = sum(x ** 2 for x in signal) / n
        e_freq = sum(abs(x) ** 2 for x in spec) / n ** 2
        self.assertAlmostEqual(e_time, e_freq, places=6)

    def test_non_power_of_2_padded(self):
        signal = [1.0] * 100  # padded to 128
        spec = fft(signal)
        self.assertEqual(len(spec), 128)

    def test_empty_input(self):
        self.assertEqual(fft([]), [])

    def test_all_zeros(self):
        spec = fft([0.0] * 64)
        self.assertAlmostEqual(max(abs(x) for x in spec), 0.0, places=10)

    def test_magnitude_spectrum_length(self):
        n = 4096
        signal = [0.0] * n
        ms = magnitude_spectrum(signal)
        self.assertEqual(len(ms), n // 2 + 1)

    def test_spectrum_bands_peak_location(self):
        """A 1kHz tone should produce a peak near 1000 Hz."""
        n = 4096
        signal = [math.sin(2 * math.pi * 1000 * i / self.SR) for i in range(n)]
        bands = spectrum_bands(signal, self.SR, n_bins=64, f_min=20.0, f_max=8000.0)
        peak = max(bands, key=lambda b: b[1])
        self.assertGreater(peak[0], 700)
        self.assertLess(peak[0], 1300)


class TestSequencer(unittest.TestCase):
    def _seq(self, notes, bpm=120, bars=1):
        preset = {
            'oscillator': 'sine', 'filter_type': 'none',
            'attack': 0.001, 'decay': 0.05, 'sustain': 0.7, 'release': 0.05,
            'volume': 0.5,
        }
        return Sequence(
            bpm=bpm, steps_per_bar=16, bars=bars,
            tracks=[Track('test', preset, notes=notes)],
        )

    def test_empty_sequence(self):
        seq = Sequence(bpm=120, steps_per_bar=16, bars=2, tracks=[])
        l, r = render(seq)
        self.assertTrue(all(s == 0.0 for s in l))

    def test_single_note_audio(self):
        seq = self._seq([NoteEvent(step=0, pitch=69, velocity=100, gate=4.0)])
        l, r = render(seq)
        self.assertGreater(_peak(l), 0.001)

    def test_step_samples_correct(self):
        """Step duration: 60/(bpm * steps_per_beat) seconds."""
        seq = Sequence(bpm=120, steps_per_bar=16, bars=1)
        expected = int(60.0 / 120 / 4 * 44100)
        self.assertEqual(seq.step_samples, expected)

    def test_out_of_range_step_ignored(self):
        preset = {'oscillator': 'sine', 'filter_type': 'none',
                  'attack': 0.01, 'decay': 0.1, 'sustain': 0.7, 'release': 0.1, 'volume': 0.5}
        seq = Sequence(bpm=120, steps_per_bar=16, bars=1, tracks=[
            Track('t', preset, notes=[NoteEvent(step=9999, pitch=60, velocity=100, gate=1.0)])
        ])
        l, r = render(seq)
        self.assertAlmostEqual(_peak(l), 0.0, places=6)

    def test_polyphony(self):
        """Two overlapping notes should produce higher amplitude than one."""
        seq1 = self._seq([NoteEvent(step=0, pitch=60, velocity=100, gate=4.0)])
        seq2 = self._seq([
            NoteEvent(step=0, pitch=60, velocity=100, gate=4.0),
            NoteEvent(step=0, pitch=67, velocity=100, gate=4.0),
        ])
        l1, _ = render(seq1)
        l2, _ = render(seq2)
        # Two voices should be louder
        self.assertGreater(_peak(l2), _peak(l1) * 1.2)

    def test_drum_track(self):
        seq = Sequence(bpm=120, steps_per_bar=16, bars=1, tracks=[
            Track('drums', {}, notes=[
                NoteEvent(step=0, pitch=0, velocity=100, gate=1.0, kind='kick'),
                NoteEvent(step=4, pitch=0, velocity=90, gate=1.0, kind='snare'),
            ], is_drum=True),
        ])
        l, r = render(seq)
        self.assertGreater(_peak(l), 0.001)

    def test_stereo_panning(self):
        """A track panned hard left should have more left than right."""
        preset = {'oscillator': 'sine', 'filter_type': 'none',
                  'attack': 0.001, 'decay': 0.05, 'sustain': 0.7, 'release': 0.05,
                  'volume': 0.8}
        seq = Sequence(bpm=120, steps_per_bar=16, bars=1, tracks=[
            Track('t', preset, notes=[NoteEvent(0, 60, 100, 8.0)], pan=-1.0)
        ])
        l, r = render(seq)
        self.assertGreater(_peak(l), _peak(r) * 5)


class TestComposer(unittest.TestCase):
    def test_all_styles_produce_tracks(self):
        for style in STYLES:
            seq = compose(key=60, style=style, bars=4, seed=42)
            self.assertGreater(len(seq.tracks), 0)
            has_melody = any(t.name == 'melody' for t in seq.tracks)
            self.assertTrue(has_melody, f'{style} has no melody track')

    def test_deterministic(self):
        seq_a = compose(key=60, style='pop', bars=4, seed=12345)
        seq_b = compose(key=60, style='pop', bars=4, seed=12345)
        notes_a = [(e.step, e.pitch) for e in seq_a.tracks[0].notes]
        notes_b = [(e.step, e.pitch) for e in seq_b.tracks[0].notes]
        self.assertEqual(notes_a, notes_b)

    def test_different_seeds_differ(self):
        seq_a = compose(key=60, style='pop', bars=4, seed=1)
        seq_b = compose(key=60, style='pop', bars=4, seed=2)
        notes_a = [(e.step, e.pitch) for e in seq_a.tracks[0].notes]
        notes_b = [(e.step, e.pitch) for e in seq_b.tracks[0].notes]
        self.assertNotEqual(notes_a, notes_b)

    def test_scale_membership(self):
        """Melody notes should belong to the chosen scale."""
        from synth.composer import SCALES
        root = 60  # C
        seq = compose(key=root, style='pop', bars=4, seed=42)
        scale = SCALES['major']
        melody = seq.tracks[0]
        for evt in melody.notes:
            semitone = (evt.pitch - root) % 12
            self.assertIn(semitone, scale,
                          f'Pitch {evt.pitch} (semitone {semitone}) not in major scale')

    def test_bpm_auto(self):
        for style in STYLES:
            seq = compose(key=60, style=style, bars=2, seed=1)
            lo, hi = STYLES[style]['bpm_range']
            self.assertGreaterEqual(seq.bpm, lo)
            self.assertLessEqual(seq.bpm, hi)

    def test_drum_events_valid(self):
        """Drum events should have recognized kind strings."""
        from synth.voice import render_drum
        valid_kinds = {'kick', 'snare', 'hihat', 'open_hihat', 'clap'}
        seq = compose(key=60, style='pop', bars=4, seed=42)
        drum_track = next((t for t in seq.tracks if t.is_drum), None)
        if drum_track:
            for evt in drum_track.notes:
                self.assertIn(evt.kind, valid_kinds,
                              f'Unknown drum kind: {evt.kind!r}')

    def test_renders_without_error(self):
        """A composed sequence should render to audio without exceptions."""
        seq = compose(key=60, style='electronic', bars=4, seed=99)
        rng = random.Random(99)
        l, r = render(seq, rng=rng)
        self.assertGreater(len(l), 0)
        self.assertGreater(_peak(l), 0.001)


class TestCLIIntegration(unittest.TestCase):
    def test_compose_pop(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            out = f.name
        try:
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, 'cadence.py', 'compose',
                 '--key', 'C', '--style', 'pop', '--bpm', '120',
                 '--bars', '2', '--seed', '1', '--output', out],
                capture_output=True, text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(out))
            l, r, sr = wav_load(out)
            self.assertEqual(sr, 44100)
            self.assertGreater(len(l), 0)
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_synth_command(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            out = f.name
        try:
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, 'cadence.py', 'synth',
                 '--note', 'A4', '--waveform', 'sine',
                 '--duration', '1.0', '--output', out],
                capture_output=True, text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            l, r, sr = wav_load(out)
            self.assertGreater(_peak(l), 0.001)
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_visualize_command(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wavf, \
             tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w') as htmlf:
            wav_path = wavf.name
            html_path = htmlf.name
        try:
            # First create a WAV
            import math
            l = [math.sin(2 * math.pi * 440 * i / 44100) * 0.5 for i in range(44100)]
            wav_save(wav_path, l, l)

            import subprocess, sys
            result = subprocess.run(
                [sys.executable, 'cadence.py', 'visualize',
                 '--input', wav_path, '--output', html_path],
                capture_output=True, text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(html_path) as f:
                html = f.read()
            self.assertIn('<audio', html)
            self.assertIn('data:audio/wav;base64,', html)
        finally:
            for p in [wav_path, html_path]:
                if os.path.exists(p):
                    os.unlink(p)


if __name__ == '__main__':
    unittest.main(verbosity=2)
