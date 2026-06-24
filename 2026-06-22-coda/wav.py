"""WAV audio buffer and file writer — 44100 Hz, 16-bit, stereo."""

import struct
import math

SAMPLE_RATE = 44100
MAX_AMPLITUDE = 32767  # int16 max


class AudioBuffer:
    """Floating-point stereo audio buffer. Samples in [-1.0, 1.0]."""

    def __init__(self, num_samples: int):
        self.num_samples = num_samples
        self.left = [0.0] * num_samples
        self.right = [0.0] * num_samples

    @classmethod
    def from_seconds(cls, duration_s: float) -> "AudioBuffer":
        return cls(int(duration_s * SAMPLE_RATE) + 1)

    def mix_into(self, other: "AudioBuffer", offset: int = 0, gain: float = 1.0):
        """Add samples from `other` into self starting at sample `offset`."""
        end = min(self.num_samples, offset + other.num_samples)
        for i in range(offset, end):
            j = i - offset
            self.left[i] += other.left[j] * gain
            self.right[i] += other.right[j] * gain

    def apply_gain(self, gain: float):
        for i in range(self.num_samples):
            self.left[i] *= gain
            self.right[i] *= gain

    def normalize(self, target: float = 0.9):
        """Scale so peak amplitude equals target (boosts quiet audio too)."""
        peak = max(
            max(abs(s) for s in self.left) if self.left else 0.0,
            max(abs(s) for s in self.right) if self.right else 0.0,
        )
        if peak > 1e-6:
            scale = target / peak
            self.apply_gain(scale)

    def peak(self) -> float:
        if not self.left:
            return 0.0
        return max(
            max(abs(s) for s in self.left),
            max(abs(s) for s in self.right),
        )

    def write_wav(self, path: str):
        """Write to a standard 16-bit stereo WAV file."""
        num_channels = 2
        bits = 16
        block_align = num_channels * (bits // 8)
        byte_rate = SAMPLE_RATE * block_align
        data_size = self.num_samples * block_align

        with open(path, "wb") as f:
            # RIFF header
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + data_size))
            f.write(b"WAVE")
            # fmt chunk
            f.write(b"fmt ")
            f.write(struct.pack("<I", 16))       # chunk size
            f.write(struct.pack("<H", 1))         # PCM
            f.write(struct.pack("<H", num_channels))
            f.write(struct.pack("<I", SAMPLE_RATE))
            f.write(struct.pack("<I", byte_rate))
            f.write(struct.pack("<H", block_align))
            f.write(struct.pack("<H", bits))
            # data chunk
            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            for i in range(self.num_samples):
                l = int(max(-1.0, min(1.0, self.left[i])) * MAX_AMPLITUDE)
                r = int(max(-1.0, min(1.0, self.right[i])) * MAX_AMPLITUDE)
                f.write(struct.pack("<hh", l, r))

    @classmethod
    def read_wav(cls, path: str) -> "AudioBuffer":
        """Read a 16-bit stereo WAV file back into an AudioBuffer."""
        with open(path, "rb") as f:
            riff = f.read(4)
            if riff != b"RIFF":
                raise ValueError("Not a RIFF file")
            f.read(4)  # chunk size
            wave = f.read(4)
            if wave != b"WAVE":
                raise ValueError("Not a WAVE file")
            # find fmt and data chunks
            fmt_data = None
            pcm_samples = None
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                chunk_id = header[:4]
                chunk_size = struct.unpack("<I", header[4:])[0]
                chunk_data = f.read(chunk_size)
                if chunk_id == b"fmt ":
                    fmt_data = chunk_data
                elif chunk_id == b"data":
                    pcm_samples = chunk_data
            if fmt_data is None or pcm_samples is None:
                raise ValueError("Missing fmt or data chunk")
            audio_fmt = struct.unpack("<H", fmt_data[0:2])[0]
            channels = struct.unpack("<H", fmt_data[2:4])[0]
            sr = struct.unpack("<I", fmt_data[4:8])[0]
            bits = struct.unpack("<H", fmt_data[14:16])[0]
            if audio_fmt != 1:
                raise ValueError("Only PCM WAV supported")
            if channels != 2:
                raise ValueError("Only stereo WAV supported")
            if bits != 16:
                raise ValueError("Only 16-bit WAV supported")
            num_samples = len(pcm_samples) // (channels * (bits // 8))
            buf = cls(num_samples)
            for i in range(num_samples):
                l, r = struct.unpack_from("<hh", pcm_samples, i * 4)
                buf.left[i] = l / MAX_AMPLITUDE
                buf.right[i] = r / MAX_AMPLITUDE
            return buf


def midi_note_to_hz(note: int) -> float:
    """Convert a MIDI note number (0-127) to frequency in Hz."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))
