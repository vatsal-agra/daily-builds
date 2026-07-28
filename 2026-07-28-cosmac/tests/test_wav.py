"""Tests for the from-scratch WAV renderer: the beep timeline capture
against the real CPU, the square-wave synthesis math, and the hand-written
RIFF/WAVE header (cross-checked by decoding it back with the stdlib
`wave` module, which is a fair independent judge of a `.wav` file's
validity even though it isn't used to *write* the file)."""
import os
import struct
import unittest
import wave

from cosmac.assembler import assemble
from cosmac.cpu import Chip8
from cosmac.debugger import Debugger
from cosmac.wav import (
    SAMPLE_RATE,
    capture_beep_timeline,
    render_program_to_wav,
    synthesize_square_wave,
    write_wav,
)

PROGRAMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "programs")
SCRATCH_WAV = "/tmp/cosmac_test_output.wav"


class TestBeepTimeline(unittest.TestCase):
    def test_timeline_matches_beep_asm_pattern(self):
        with open(os.path.join(PROGRAMS_DIR, "beep.asm")) as f:
            prog = assemble(f.read())
        cpu = Chip8()
        cpu.load(prog)
        dbg = Debugger(cpu)
        timeline = capture_beep_timeline(dbg, 250)

        # collapse into runs of (value, length)
        runs = []
        cur, count = timeline[0], 0
        for v in timeline:
            if v == cur:
                count += 1
            else:
                runs.append((cur, count))
                cur, count = v, 1
        runs.append((cur, count))

        beep_runs = [r for r in runs if r[0] is True]
        self.assertEqual(len(beep_runs), 4, "beep.asm should produce exactly 4 beeps")
        for _, length in beep_runs:
            self.assertAlmostEqual(length, 30, delta=2)

    def test_program_with_no_sound_produces_an_all_silent_timeline(self):
        with open(os.path.join(PROGRAMS_DIR, "ball.asm")) as f:
            prog = assemble(f.read())
        cpu = Chip8()
        cpu.load(prog)
        dbg = Debugger(cpu)
        timeline = capture_beep_timeline(dbg, 100)
        self.assertTrue(all(v is False for v in timeline))


class TestSquareWaveSynthesis(unittest.TestCase):
    def test_silence_is_all_zero_samples(self):
        samples = synthesize_square_wave([False, False, False])
        self.assertTrue(all(s == 0 for s in samples))

    def test_beep_alternates_between_positive_and_negative_amplitude(self):
        samples = synthesize_square_wave([True] * 10, amplitude=1234)
        self.assertTrue(all(s in (1234, -1234) for s in samples))
        self.assertIn(1234, samples)
        self.assertIn(-1234, samples)

    def test_sample_count_matches_tick_count_times_samples_per_tick(self):
        samples = synthesize_square_wave([True, False, True], sample_rate=44100, tick_hz=60)
        self.assertEqual(len(samples), 3 * (44100 // 60))


class TestWavFileFormat(unittest.TestCase):
    def test_written_wav_is_valid_per_stdlib_wave_module(self):
        samples = synthesize_square_wave([True, False, True, True], sample_rate=8000)
        write_wav(SCRATCH_WAV, samples, sample_rate=8000)
        try:
            with wave.open(SCRATCH_WAV, "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getframerate(), 8000)
                self.assertEqual(w.getnframes(), len(samples))
                frames = w.readframes(w.getnframes())
                decoded = struct.unpack(f"<{len(samples)}h", frames)
                self.assertEqual(list(decoded), samples)
        finally:
            os.remove(SCRATCH_WAV)

    def test_header_byte_layout(self):
        write_wav(SCRATCH_WAV, [0, 100, -100], sample_rate=44100)
        try:
            with open(SCRATCH_WAV, "rb") as f:
                header = f.read(44)
            self.assertEqual(header[0:4], b"RIFF")
            self.assertEqual(header[8:12], b"WAVE")
            self.assertEqual(header[12:16], b"fmt ")
            self.assertEqual(struct.unpack("<H", header[20:22])[0], 1)   # PCM
            self.assertEqual(struct.unpack("<H", header[22:24])[0], 1)   # mono
            self.assertEqual(struct.unpack("<I", header[24:28])[0], 44100)
            self.assertEqual(header[36:40], b"data")
            self.assertEqual(struct.unpack("<I", header[40:44])[0], 3 * 2)
        finally:
            os.remove(SCRATCH_WAV)

    def test_render_program_to_wav_end_to_end(self):
        with open(os.path.join(PROGRAMS_DIR, "beep.asm")) as f:
            prog = assemble(f.read())
        timeline = render_program_to_wav(prog, SCRATCH_WAV, ticks=200)
        try:
            self.assertTrue(any(timeline))   # at least one beep captured
            with wave.open(SCRATCH_WAV, "rb") as w:
                self.assertEqual(w.getframerate(), SAMPLE_RATE)
                self.assertEqual(w.getnframes(), len(timeline) * (SAMPLE_RATE // 60))
        finally:
            os.remove(SCRATCH_WAV)


if __name__ == "__main__":
    unittest.main()
