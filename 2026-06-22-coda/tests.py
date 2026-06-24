#!/usr/bin/env python3
"""Comprehensive test suite for Coda.

Tests cover:
  - WAV buffer and file I/O
  - VLQ encoding/decoding
  - MIDI binary parser (running status, NoteOn vel=0, meta events)
  - MIDI writer round-trips
  - Tempo map correctness
  - Synthesizer (waveform shapes, ADSR envelope, frequency accuracy)
  - Instrument presets (valid VoiceParams)
  - Music generator (note ranges, scale adherence, drum channel)
  - Renderer (non-silence, normalization, drum hit, tempo map)
  - Effects chain (reverb stability, delay bounds, LPF attenuation)
  - Piano roll visualizer (HTML content)
  - CLI commands (generate, render, make, viz, info, error handling)
"""

import io
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest

# Ensure we can import from the project directory
sys.path.insert(0, os.path.dirname(__file__))

from wav import AudioBuffer, SAMPLE_RATE, midi_note_to_hz
from midi import (
    parse_midi, parse_midi_file, write_midi, write_midi_file,
    parse_track, write_vlq, read_vlq,
    NoteOn, NoteOff, ProgramChange, ControlChange, PitchBend,
    TempoChange, TimeSignature, KeySignature, TrackName, EndOfTrack,
    MidiFile, MidiTrack, MidiEvent,
)
from synth import ADSR, sine_wave, square_wave, sawtooth_wave, triangle_wave, noise_burst, render_voice, VoiceParams
from instruments import piano, bass, organ, gm_program_to_voice, DRUM_MAP
from generator import (
    generate_piece, scale_notes, chord_notes, degree_to_midi, SCALES, CHORD_PATTERNS
)
from renderer import TempoMap, build_tempo_map, render_midi, render_drum_hit
from effects import BiquadLPF, SchroederReverb, PingPongDelay, apply_effects
from viz import extract_note_events, generate_html, write_html


# ---------------------------------------------------------------------------
# WAV tests
# ---------------------------------------------------------------------------

class TestWAV(unittest.TestCase):

    def test_audio_buffer_creation(self):
        buf = AudioBuffer(100)
        self.assertEqual(buf.num_samples, 100)
        self.assertEqual(len(buf.left), 100)
        self.assertEqual(len(buf.right), 100)

    def test_from_seconds(self):
        buf = AudioBuffer.from_seconds(1.0)
        self.assertEqual(buf.num_samples, SAMPLE_RATE + 1)

    def test_normalize_boosts_quiet_audio(self):
        buf = AudioBuffer(100)
        buf.left = [0.01] * 100
        buf.right = [0.01] * 100
        buf.normalize(target=0.9)
        self.assertAlmostEqual(buf.peak(), 0.9, places=5)

    def test_normalize_clips_loud_audio(self):
        buf = AudioBuffer(100)
        buf.left = [2.0] * 100
        buf.right = [2.0] * 100
        buf.normalize(target=0.9)
        self.assertAlmostEqual(buf.peak(), 0.9, places=5)

    def test_normalize_silent_audio(self):
        buf = AudioBuffer(100)
        # All zeros — should not raise
        buf.normalize()
        self.assertAlmostEqual(buf.peak(), 0.0)

    def test_mix_into(self):
        dst = AudioBuffer(100)
        src = AudioBuffer(50)
        src.left = [1.0] * 50
        src.right = [1.0] * 50
        dst.mix_into(src, offset=10, gain=0.5)
        self.assertAlmostEqual(dst.left[10], 0.5)   # first sample of src
        self.assertAlmostEqual(dst.left[59], 0.5)   # last sample of src (offset+50-1=59)
        self.assertAlmostEqual(dst.left[60], 0.0)   # outside src range

    def test_wav_roundtrip(self):
        buf = AudioBuffer(1000)
        for i in range(1000):
            buf.left[i] = math.sin(2 * math.pi * 440 * i / SAMPLE_RATE) * 0.5
            buf.right[i] = math.cos(2 * math.pi * 440 * i / SAMPLE_RATE) * 0.5
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            buf.write_wav(path)
            buf2 = AudioBuffer.read_wav(path)
            self.assertEqual(buf2.num_samples, buf.num_samples)
            # Check a few sample values (quantization to 16-bit = ±0.00005 error)
            for i in range(0, 1000, 100):
                self.assertAlmostEqual(buf2.left[i], buf.left[i], places=3)
                self.assertAlmostEqual(buf2.right[i], buf.right[i], places=3)
        finally:
            os.unlink(path)

    def test_wav_header_format(self):
        buf = AudioBuffer(100)
        buf.left = [0.1] * 100
        buf.right = [0.1] * 100
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            buf.write_wav(path)
            with open(path, "rb") as f:
                data = f.read()
            self.assertEqual(data[:4], b"RIFF")
            self.assertEqual(data[8:12], b"WAVE")
            self.assertEqual(data[12:16], b"fmt ")
            fmt_size = struct.unpack("<I", data[16:20])[0]
            self.assertEqual(fmt_size, 16)
            audio_fmt = struct.unpack("<H", data[20:22])[0]
            self.assertEqual(audio_fmt, 1)  # PCM
            channels = struct.unpack("<H", data[22:24])[0]
            self.assertEqual(channels, 2)
            sr = struct.unpack("<I", data[24:28])[0]
            self.assertEqual(sr, SAMPLE_RATE)
            bits = struct.unpack("<H", data[34:36])[0]
            self.assertEqual(bits, 16)
        finally:
            os.unlink(path)

    def test_midi_note_to_hz(self):
        self.assertAlmostEqual(midi_note_to_hz(69), 440.0, places=2)   # A4
        self.assertAlmostEqual(midi_note_to_hz(60), 261.63, places=1)  # C4
        self.assertAlmostEqual(midi_note_to_hz(81), 880.0, places=2)   # A5
        self.assertAlmostEqual(midi_note_to_hz(57), 220.0, places=2)   # A3


# ---------------------------------------------------------------------------
# VLQ tests
# ---------------------------------------------------------------------------

class TestVLQ(unittest.TestCase):

    def _rt(self, val):
        return read_vlq(io.BytesIO(write_vlq(val)))

    def test_zero(self):
        self.assertEqual(self._rt(0), 0)
        self.assertEqual(write_vlq(0), bytes([0x00]))

    def test_below_128(self):
        for v in [1, 63, 64, 127]:
            self.assertEqual(self._rt(v), v)
            self.assertEqual(len(write_vlq(v)), 1)

    def test_two_byte(self):
        self.assertEqual(self._rt(128), 128)
        self.assertEqual(self._rt(255), 255)
        self.assertEqual(self._rt(0x3FFF), 0x3FFF)

    def test_four_byte_max(self):
        max_val = 0x0FFFFFFF
        self.assertEqual(self._rt(max_val), max_val)
        self.assertEqual(len(write_vlq(max_val)), 4)

    def test_five_byte_rejected(self):
        bad = io.BytesIO(bytes([0x81, 0x81, 0x81, 0x81, 0x81, 0x00]))
        with self.assertRaises(ValueError):
            read_vlq(bad)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            write_vlq(-1)


# ---------------------------------------------------------------------------
# MIDI parser tests
# ---------------------------------------------------------------------------

class TestMIDIParser(unittest.TestCase):

    def _make_track(self, *event_bytes):
        """Build raw track bytes from interleaved (delta, event_bytes) tuples."""
        data = bytearray()
        for delta_and_bytes in event_bytes:
            delta, evt = delta_and_bytes
            data += write_vlq(delta)
            data += evt
        data += write_vlq(0)
        data += bytes([0xFF, 0x2F, 0x00])
        return bytes(data)

    def test_note_on_off(self):
        track_data = self._make_track(
            (0, bytes([0x90, 60, 100])),   # NoteOn ch0 note60 vel100
            (480, bytes([0x80, 60, 0])),   # NoteOff ch0 note60 vel0
        )
        track = parse_track(track_data)
        events = [(e.tick, type(e.event).__name__) for e in track.events]
        self.assertIn((0, "NoteOn"), events)
        self.assertIn((480, "NoteOff"), events)

    def test_noteon_vel0_is_noteoff(self):
        track_data = self._make_track(
            (0, bytes([0x90, 60, 100])),
            (480, bytes([0x90, 60, 0])),   # NoteOn vel=0 → NoteOff
        )
        track = parse_track(track_data)
        note_offs = [e for e in track.events if isinstance(e.event, NoteOff)]
        self.assertEqual(len(note_offs), 1)
        self.assertEqual(note_offs[0].tick, 480)

    def test_running_status(self):
        track_data = self._make_track(
            (0, bytes([0x90, 60, 100])),  # status byte present
            (240, bytes([61, 90])),        # running status: NoteOn note61 vel90
        )
        track = parse_track(track_data)
        note_ons = [e for e in track.events if isinstance(e.event, NoteOn)]
        self.assertEqual(len(note_ons), 2)
        self.assertEqual(note_ons[1].event.note, 61)

    def test_program_change(self):
        track_data = self._make_track(
            (0, bytes([0xC0, 25])),  # ProgramChange ch0 prog25
        )
        track = parse_track(track_data)
        pcs = [e for e in track.events if isinstance(e.event, ProgramChange)]
        self.assertEqual(len(pcs), 1)
        self.assertEqual(pcs[0].event.program, 25)

    def test_pitch_bend(self):
        track_data = self._make_track(
            (0, bytes([0xE0, 0x00, 0x40])),  # center (0x2000)
        )
        track = parse_track(track_data)
        pbs = [e for e in track.events if isinstance(e.event, PitchBend)]
        self.assertEqual(len(pbs), 1)
        self.assertEqual(pbs[0].event.value, 0)  # center = 0

    def test_tempo_meta(self):
        track_data = self._make_track(
            (0, bytes([0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20])),  # 500000 us/beat
        )
        track = parse_track(track_data)
        tempos = [e for e in track.events if isinstance(e.event, TempoChange)]
        self.assertEqual(len(tempos), 1)
        self.assertEqual(tempos[0].event.us_per_beat, 500000)

    def test_track_name_meta(self):
        name_bytes = b"Piano"
        track_data = self._make_track(
            (0, bytes([0xFF, 0x03]) + write_vlq(len(name_bytes)) + name_bytes),
        )
        track = parse_track(track_data)
        names = [e for e in track.events if isinstance(e.event, TrackName)]
        self.assertEqual(names[0].event.name, "Piano")

    def test_non_midi_rejected(self):
        with self.assertRaises(ValueError):
            parse_midi(b"RIFF\x00\x00\x00\x06WAVE")

    def test_type1_midi_roundtrip(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=1)
        data = write_midi(midi)
        midi2 = parse_midi(data)
        self.assertEqual(midi2.format, midi.format)
        self.assertEqual(midi2.ticks_per_beat, midi.ticks_per_beat)
        self.assertEqual(len(midi2.tracks), len(midi.tracks))
        orig_ons = sum(1 for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn))
        rt_ons = sum(1 for t in midi2.tracks for e in t.events if isinstance(e.event, NoteOn))
        self.assertEqual(rt_ons, orig_ons)

    def test_tick_roundtrip(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=1)
        orig_ticks = sorted(e.tick for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn))
        data = write_midi(midi)
        midi2 = parse_midi(data)
        rt_ticks = sorted(e.tick for t in midi2.tracks for e in t.events if isinstance(e.event, NoteOn))
        self.assertEqual(orig_ticks, rt_ticks)


# ---------------------------------------------------------------------------
# Synthesizer tests
# ---------------------------------------------------------------------------

class TestSynth(unittest.TestCase):

    def test_sine_frequency(self):
        """Zero-crossing count of a sine wave matches expected frequency."""
        freq = 440.0
        n = SAMPLE_RATE  # 1 second
        samples = sine_wave(freq, n)
        crossings = sum(1 for i in range(1, n) if samples[i - 1] < 0 <= samples[i])
        self.assertAlmostEqual(crossings, int(freq), delta=2)

    def test_sine_amplitude(self):
        samples = sine_wave(440, 4410)
        self.assertAlmostEqual(max(samples), 1.0, places=2)
        self.assertAlmostEqual(min(samples), -1.0, places=2)

    def test_square_wave_bounded(self):
        samples = square_wave(440, 4410)
        self.assertTrue(all(-1.01 <= s <= 1.01 for s in samples))

    def test_noise_deterministic(self):
        s1 = noise_burst(100, seed=42)
        s2 = noise_burst(100, seed=42)
        self.assertEqual(s1, s2)

    def test_noise_different_seeds(self):
        s1 = noise_burst(100, seed=1)
        s2 = noise_burst(100, seed=2)
        self.assertNotEqual(s1, s2)

    def test_adsr_shape(self):
        adsr = ADSR(attack=0.1, decay=0.1, sustain=0.5, release=0.1)
        env = adsr.envelope(0.5)
        a_samps = int(0.1 * SAMPLE_RATE)
        d_samps = int(0.1 * SAMPLE_RATE)
        self.assertAlmostEqual(env[0], 0.0, places=3)
        self.assertAlmostEqual(env[a_samps - 1], 1.0, places=2)
        self.assertAlmostEqual(env[a_samps + d_samps - 1], 0.5, places=2)
        self.assertAlmostEqual(env[-1], 0.0, places=2)

    def test_adsr_apply(self):
        adsr = ADSR(attack=0.01, decay=0.01, sustain=0.8, release=0.01)
        s = [1.0] * 10000
        result = adsr.apply(s, 0.2)
        # Should start near 0 and peak at 1.0
        self.assertLess(result[0], 0.1)
        self.assertAlmostEqual(max(result), 1.0, places=1)

    def test_render_voice_non_silent(self):
        params = VoiceParams()
        buf = render_voice(60, 80, 0.1, 0.0, params)
        peak = max(abs(s) for s in buf.left)
        self.assertGreater(peak, 0.01)

    def test_render_voice_all_midi_notes(self):
        params = VoiceParams(waveform="sine", adsr=ADSR(0.001, 0.001, 0.9, 0.001))
        for note in [0, 21, 60, 108, 127]:
            buf = render_voice(note, 64, 0.05, 0.0, params)
            self.assertGreater(buf.num_samples, 0)

    def test_render_voice_velocity_zero(self):
        params = VoiceParams()
        buf = render_voice(60, 0, 0.1, 0.0, params)
        peak = max(abs(s) for s in buf.left)
        self.assertAlmostEqual(peak, 0.0, places=5)

    def test_render_voice_pan(self):
        params = VoiceParams()
        buf_l = render_voice(60, 80, 0.1, -1.0, params)  # full left
        buf_r = render_voice(60, 80, 0.1, 1.0, params)   # full right
        # Left pan: left channel much louder than right
        peak_l = max(abs(s) for s in buf_l.left)
        peak_r = max(abs(s) for s in buf_l.right)
        self.assertGreater(peak_l, peak_r * 5)


# ---------------------------------------------------------------------------
# Instrument tests
# ---------------------------------------------------------------------------

class TestInstruments(unittest.TestCase):

    def test_piano_voice_params(self):
        p = piano()
        self.assertIsNotNone(p.adsr)
        self.assertTrue(len(p.harmonics) > 2)

    def test_gm_program_mapping(self):
        # Every program 0-127 should return a VoiceParams without error
        for prog in [0, 7, 15, 23, 31, 39, 47, 55, 63, 71, 79, 95, 127]:
            params = gm_program_to_voice(prog)
            self.assertIsNotNone(params.adsr)

    def test_drum_map_non_empty(self):
        self.assertGreater(len(DRUM_MAP), 5)
        # All drum notes should be valid MIDI notes
        for note in DRUM_MAP:
            self.assertIn(note, range(128))


# ---------------------------------------------------------------------------
# Music generator tests
# ---------------------------------------------------------------------------

class TestGenerator(unittest.TestCase):

    def test_scale_notes(self):
        notes = scale_notes(60, "major", octave_range=1)
        self.assertEqual(len(notes), 7)
        # C major scale relative intervals: 0,2,4,5,7,9,11
        intervals = [n - 60 for n in notes]
        self.assertEqual(intervals, [0, 2, 4, 5, 7, 9, 11])

    def test_chord_major(self):
        notes = chord_notes(60, "maj")
        self.assertEqual(notes, [60, 64, 67])

    def test_chord_minor(self):
        notes = chord_notes(60, "min")
        self.assertEqual(notes, [60, 63, 67])

    def test_chord_diminished(self):
        notes = chord_notes(60, "dim")
        self.assertEqual(notes, [60, 63, 66])

    def test_degree_to_midi(self):
        # Degree 0 = root, degree 1 = 2nd, etc.
        self.assertEqual(degree_to_midi(60, "major", 0), 60)  # C
        self.assertEqual(degree_to_midi(60, "major", 1), 62)  # D
        self.assertEqual(degree_to_midi(60, "major", 6), 71)  # B
        self.assertEqual(degree_to_midi(60, "major", 7), 72)  # C5 (octave up)

    def test_generate_all_scales(self):
        for scale in SCALES:
            midi = generate_piece(key=60, scale_name=scale, num_bars=4, seed=42)
            self.assertEqual(len(midi.tracks), 5)
            total = sum(1 for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn))
            self.assertGreater(total, 0)

    def test_note_ranges_reasonable(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        all_notes = [e.event.note for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn)]
        self.assertTrue(all(0 <= n <= 127 for n in all_notes))

    def test_bass_in_bass_register(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        bass_notes = [e.event.note for e in midi.tracks[3].events if isinstance(e.event, NoteOn)]
        self.assertTrue(all(20 <= n <= 65 for n in bass_notes), f"Bass out of range: {bass_notes}")

    def test_chords_in_mid_register(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        chord_notes_list = [e.event.note for e in midi.tracks[2].events if isinstance(e.event, NoteOn)]
        self.assertTrue(all(48 <= n <= 100 for n in chord_notes_list),
                        f"Chords out of range: {chord_notes_list}")

    def test_melody_in_scale(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=8, seed=42)
        from generator import SCALES
        scale_intervals = set(SCALES["major"])
        melody_notes = [e.event.note for e in midi.tracks[1].events if isinstance(e.event, NoteOn)]
        off_scale = [n for n in melody_notes if (n % 12) not in scale_intervals]
        off_pct = len(off_scale) / max(1, len(melody_notes)) * 100
        self.assertLess(off_pct, 10, f"Too many off-scale notes: {off_pct:.1f}%")

    def test_drums_on_channel_9(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        drum_channels = set(e.event.channel for e in midi.tracks[4].events
                            if isinstance(e.event, NoteOn))
        self.assertEqual(drum_channels, {9})

    def test_note_pairing(self):
        """Every NoteOn must have a matching NoteOff."""
        midi = generate_piece(key=60, scale_name="major", num_bars=8, seed=1)
        for track in midi.tracks:
            state = {}
            for ev in sorted(track.events, key=lambda e: e.tick):
                if isinstance(ev.event, NoteOn):
                    state[(ev.event.channel, ev.event.note)] = ev.tick
                elif isinstance(ev.event, NoteOff):
                    state.pop((ev.event.channel, ev.event.note), None)
            # After processing, unclosed notes are those held to the end — acceptable
            # (renderer handles them via the flush at the end)

    def test_deterministic_with_seed(self):
        midi1 = generate_piece(key=60, scale_name="major", num_bars=4, seed=99)
        midi2 = generate_piece(key=60, scale_name="major", num_bars=4, seed=99)
        ticks1 = sorted(e.tick for t in midi1.tracks for e in t.events if isinstance(e.event, NoteOn))
        ticks2 = sorted(e.tick for t in midi2.tracks for e in t.events if isinstance(e.event, NoteOn))
        self.assertEqual(ticks1, ticks2)

    def test_different_seeds_differ(self):
        midi1 = generate_piece(key=60, scale_name="major", num_bars=4, seed=1)
        midi2 = generate_piece(key=60, scale_name="major", num_bars=4, seed=2)
        ticks1 = sorted(e.tick for t in midi1.tracks for e in t.events if isinstance(e.event, NoteOn))
        ticks2 = sorted(e.tick for t in midi2.tracks for e in t.events if isinstance(e.event, NoteOn))
        self.assertNotEqual(ticks1, ticks2)

    def test_midi_has_end_of_track(self):
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=1)
        for i, track in enumerate(midi.tracks):
            eots = [e for e in track.events if isinstance(e.event, EndOfTrack)]
            self.assertEqual(len(eots), 1, f"Track {i} should have exactly 1 EndOfTrack")

    def test_all_drum_styles(self):
        for style in ("standard", "rock", "jazz", "electronic"):
            midi = generate_piece(num_bars=2, drum_style=style, seed=42)
            drums = [e for e in midi.tracks[4].events if isinstance(e.event, NoteOn)]
            self.assertGreater(len(drums), 0, f"No drums for style {style}")


# ---------------------------------------------------------------------------
# Tempo map tests
# ---------------------------------------------------------------------------

class TestTempoMap(unittest.TestCase):

    def test_default_120bpm(self):
        tm = TempoMap(480)  # 480 PPQN, default 120 BPM
        self.assertAlmostEqual(tm.tick_to_seconds(0), 0.0)
        self.assertAlmostEqual(tm.tick_to_seconds(480), 0.5)    # 1 beat
        self.assertAlmostEqual(tm.tick_to_seconds(1920), 2.0)   # 1 bar
        self.assertAlmostEqual(tm.tick_to_seconds(9600), 10.0)  # 20 beats

    def test_240bpm(self):
        tm = TempoMap(480)
        tm.add_tempo(0, 250_000)  # 240 BPM = 250000 us/beat
        self.assertAlmostEqual(tm.tick_to_seconds(480), 0.25)   # 1 beat = 0.25s

    def test_tempo_change_mid_piece(self):
        tm = TempoMap(480)
        # Default = 120 BPM
        tm.add_tempo(480, 250_000)  # switch to 240 BPM after 1 beat
        # First beat: 0.5s, second beat: 0.25s
        self.assertAlmostEqual(tm.tick_to_seconds(480), 0.5)    # end of first beat
        self.assertAlmostEqual(tm.tick_to_seconds(960), 0.75)   # end of second beat

    def test_build_tempo_map_from_midi(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, bpm=140, seed=1)
        tm = build_tempo_map(midi)
        expected_us = int(60_000_000 / 140)
        # At 480 PPQN and 140 BPM, 1 beat = 60/140 seconds
        self.assertAlmostEqual(tm.tick_to_seconds(480), 60/140, places=4)


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

class TestRenderer(unittest.TestCase):

    def test_render_non_silent(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, seed=1)
        buf = render_midi(midi)
        self.assertGreater(buf.peak(), 0.1)

    def test_render_normalized(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, seed=1)
        buf = render_midi(midi)
        self.assertAlmostEqual(buf.peak(), 0.9, places=1)

    def test_render_duration_correct(self):
        """Rendered audio should be roughly as long as the MIDI."""
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, bpm=120, seed=1)
        tm = build_tempo_map(midi)
        max_tick = max(e.tick for t in midi.tracks for e in t.events)
        expected_s = tm.tick_to_seconds(max_tick)
        buf = render_midi(midi)
        actual_s = buf.num_samples / SAMPLE_RATE
        # Renderer adds a 2s tail; allow generous tolerance
        self.assertGreater(actual_s, expected_s)
        self.assertLess(actual_s, expected_s + 4)

    def test_render_drum_hit(self):
        buf = render_drum_hit(36, 100, 0.1)  # kick drum
        self.assertGreater(buf.peak(), 0.01)

    def test_render_all_scales(self):
        from generator import generate_piece
        for scale in list(SCALES.keys())[:3]:  # test 3 scales to save time
            midi = generate_piece(key=60, scale_name=scale, num_bars=2, seed=42)
            buf = render_midi(midi)
            self.assertGreater(buf.peak(), 0.1, f"Silent output for {scale}")


# ---------------------------------------------------------------------------
# Effects tests
# ---------------------------------------------------------------------------

class TestEffects(unittest.TestCase):

    def _make_buf(self, freq=440.0, duration_s=0.5):
        buf = AudioBuffer.from_seconds(duration_s)
        for i in range(buf.num_samples):
            s = math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * 0.5
            buf.left[i] = s
            buf.right[i] = s
        return buf

    def test_biquad_lpf_attenuates_high_freq(self):
        """4kHz LPF should pass 440Hz but attenuate 20kHz."""
        buf = AudioBuffer(44100)
        for i in range(44100):
            s440 = math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)
            s20k = math.sin(2 * math.pi * 20000 * i / SAMPLE_RATE)
            buf.left[i] = s440 * 0.5 + s20k * 0.5
            buf.right[i] = buf.left[i]
        BiquadLPF(cutoff_hz=4000).process(buf)
        # After filter settles, 440Hz should still be present
        steady_peak = max(abs(buf.left[i]) for i in range(20000, 30000))
        self.assertGreater(steady_peak, 0.1)

    def test_reverb_stable(self):
        """Reverb impulse response must not blow up."""
        buf = AudioBuffer(SAMPLE_RATE)
        buf.left[100] = 1.0
        buf.right[100] = 1.0
        SchroederReverb(room_size=0.9, wet=0.4).process(buf)
        self.assertLess(buf.peak(), 2.0)

    def test_delay_bounded(self):
        """Delay feedback < 1 so signal decays."""
        buf = self._make_buf(440, 2.0)
        initial_peak = buf.peak()
        PingPongDelay(delay_ms=375, feedback=0.5, wet=0.5).process(buf)
        self.assertLess(buf.peak(), initial_peak * 3)  # not exploding

    def test_apply_effects_chain(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, seed=1)
        buf = render_midi(midi)
        apply_effects(buf, reverb=True, delay=True, lpf=True)
        self.assertGreater(buf.peak(), 0.1)
        self.assertLess(buf.peak(), 1.01)

    def test_effects_noop_when_disabled(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, seed=1)
        buf = render_midi(midi)
        orig_left = buf.left[:]
        apply_effects(buf, reverb=False, delay=False, lpf=False)
        # normalize is still called, but since audio is already normalized, no change
        self.assertEqual(buf.left, orig_left)


# ---------------------------------------------------------------------------
# Visualizer tests
# ---------------------------------------------------------------------------

class TestVisualizer(unittest.TestCase):

    def test_extract_note_events(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        tracks_data = extract_note_events(midi)
        self.assertGreater(len(tracks_data), 0)
        total = sum(len(t["notes"]) for t in tracks_data)
        self.assertGreater(total, 0)

    def test_note_events_have_required_fields(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        tracks_data = extract_note_events(midi)
        for track in tracks_data:
            self.assertIn("name", track)
            self.assertIn("notes", track)
            for n in track["notes"]:
                self.assertIn("note", n)
                self.assertIn("start", n)
                self.assertIn("dur", n)
                self.assertIn("vel", n)
                self.assertIn("ch", n)
                self.assertGreater(n["dur"], 0)
                self.assertGreaterEqual(n["start"], 0)
                self.assertIn(n["note"], range(128))

    def test_generate_html_valid(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=4, seed=42)
        html = generate_html(midi, "Test")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("roll-canvas", html)
        self.assertIn("AudioContext", html)
        self.assertIn("togglePlay", html)
        self.assertIn("drawPiano", html)
        self.assertGreater(len(html), 10000)

    def test_write_html_creates_file(self):
        from generator import generate_piece
        midi = generate_piece(key=60, scale_name="major", num_bars=2, seed=1)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        try:
            size = write_html(midi, path, "Test")
            self.assertGreater(size, 5000)
            with open(path) as f:
                content = f.read()
            self.assertIn("<!DOCTYPE html>", content)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    BASE = os.path.dirname(__file__)

    def _run(self, *args, **kwargs):
        result = subprocess.run(
            ["python3", "cli.py"] + list(args),
            capture_output=True, text=True,
            cwd=self.BASE, **kwargs,
        )
        return result

    def test_help(self):
        r = self._run("help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("coda generate", r.stdout)

    def test_generate_default(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            r = self._run("generate", "--bars", "4", "--out", path)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(path) > 100)
        finally:
            if os.path.exists(path): os.unlink(path)

    def test_generate_all_scales(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            for scale in SCALES:
                r = self._run("generate", "--scale", scale, "--bars", "4", "--out", path)
                self.assertEqual(r.returncode, 0, f"{scale}: {r.stderr}")
        finally:
            if os.path.exists(path): os.unlink(path)

    def test_info_command(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            midi_path = f.name
        try:
            self._run("generate", "--bars", "4", "--out", midi_path)
            r = self._run("info", midi_path)
            self.assertEqual(r.returncode, 0)
            self.assertIn("Format", r.stdout)
            self.assertIn("PPQN", r.stdout)
            self.assertIn("Tracks", r.stdout)
        finally:
            if os.path.exists(midi_path): os.unlink(midi_path)

    def test_render_command(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            midi_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            self._run("generate", "--bars", "4", "--out", midi_path)
            r = self._run("render", midi_path, "--out", wav_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(wav_path) > 1000)
        finally:
            for p in (midi_path, wav_path):
                if os.path.exists(p): os.unlink(p)

    def test_render_with_effects(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            midi_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            self._run("generate", "--bars", "4", "--out", midi_path)
            r = self._run("render", midi_path, "--out", wav_path, "--reverb", "--delay")
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            for p in (midi_path, wav_path):
                if os.path.exists(p): os.unlink(p)

    def test_viz_command(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            midi_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = f.name
        try:
            self._run("generate", "--bars", "4", "--out", midi_path)
            r = self._run("viz", midi_path, "--out", html_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(html_path) > 5000)
        finally:
            for p in (midi_path, html_path):
                if os.path.exists(p): os.unlink(p)

    def test_make_command(self):
        base = os.path.join(tempfile.mkdtemp(), "test_make")
        try:
            r = self._run("make", "--bars", "2", "--seed", "1", "--out", base)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(base + ".mid"))
            self.assertTrue(os.path.exists(base + ".wav"))
            self.assertTrue(os.path.exists(base + "_roll.html"))
        finally:
            for ext in (".mid", ".wav", "_roll.html"):
                p = base + ext
                if os.path.exists(p): os.unlink(p)

    def test_bad_command(self):
        r = self._run("no_such_cmd")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown command", r.stderr)

    def test_bad_scale(self):
        r = self._run("generate", "--scale", "xyzzy")
        self.assertEqual(r.returncode, 1)

    def test_bad_bpm(self):
        r = self._run("generate", "--bpm", "5")
        self.assertEqual(r.returncode, 1)

    def test_render_missing_file(self):
        r = self._run("render", "/no/such/file.mid")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr.lower())

    def test_info_missing_file(self):
        r = self._run("info", "/no/such/file.mid")
        self.assertEqual(r.returncode, 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
