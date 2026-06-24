"""From-scratch WAV encoder and decoder.

Uses Python's `struct` module to pack the RIFF/WAVE header and `array` for
the sample data. The stdlib `wave` module is intentionally NOT used.

Format: 44100 Hz, 16-bit signed PCM, stereo.
"""

import struct
import array


SAMPLE_RATE = 44100
CHANNELS = 2
BITS = 16
BLOCK_ALIGN = CHANNELS * BITS // 8
BYTE_RATE = SAMPLE_RATE * BLOCK_ALIGN


def _float_to_int16(x: float) -> int:
    """Clamp to [-1,1] and scale to signed 16-bit integer."""
    clamped = max(-1.0, min(1.0, x))
    return int(clamped * 32767)


def encode(left: list, right: list) -> bytes:
    """Encode L+R float sample lists into a WAV byte string."""
    assert len(left) == len(right), "L/R must have the same length"
    n = len(left)

    # Interleave samples: L0 R0 L1 R1 ...
    pcm = array.array('h')  # signed short
    for l, r in zip(left, right):
        pcm.append(_float_to_int16(l))
        pcm.append(_float_to_int16(r))

    data_bytes = pcm.tobytes()
    data_size = len(data_bytes)
    riff_size = 36 + data_size

    header = struct.pack(
        '<4sI4s'    # "RIFF", size, "WAVE"
        '4sIHHIIHH' # "fmt ", 16, PCM=1, channels, sample_rate, byte_rate, block_align, bits
        '4sI',      # "data", data_size
        b'RIFF', riff_size, b'WAVE',
        b'fmt ', 16, 1, CHANNELS, SAMPLE_RATE, BYTE_RATE, BLOCK_ALIGN, BITS,
        b'data', data_size,
    )
    return header + data_bytes


def decode(wav_bytes: bytes) -> tuple:
    """Decode WAV bytes back to (left, right) float lists.

    Only handles standard 16-bit stereo PCM (the format we encode).
    Raises ValueError for unsupported formats.
    """
    if wav_bytes[:4] != b'RIFF' or wav_bytes[8:12] != b'WAVE':
        raise ValueError("Not a RIFF/WAVE file")

    # Parse chunks
    pos = 12
    fmt_chunk = None
    data_chunk = None
    while pos < len(wav_bytes) - 8:
        tag = wav_bytes[pos:pos+4]
        size = struct.unpack_from('<I', wav_bytes, pos + 4)[0]
        chunk = wav_bytes[pos+8:pos+8+size]
        if tag == b'fmt ':
            fmt_chunk = chunk
        elif tag == b'data':
            data_chunk = chunk
        pos += 8 + size
        if size % 2 == 1:
            pos += 1  # word-aligned

    if fmt_chunk is None or data_chunk is None:
        raise ValueError("Missing fmt or data chunk")

    audio_fmt, ch, sr, _, _, bits = struct.unpack_from('<HHIIHH', fmt_chunk)
    if audio_fmt != 1:
        raise ValueError(f"Only PCM (format 1) supported, got {audio_fmt}")
    if bits != 16:
        raise ValueError(f"Only 16-bit supported, got {bits}")
    if ch != 2:
        raise ValueError(f"Only stereo supported, got {ch} channels")

    samples = array.array('h')
    samples.frombytes(data_chunk)
    left  = [samples[i]     / 32768.0 for i in range(0, len(samples), 2)]
    right = [samples[i + 1] / 32768.0 for i in range(0, len(samples), 2)]
    return left, right, sr


def save(path: str, left: list, right: list) -> None:
    with open(path, 'wb') as f:
        f.write(encode(left, right))


def load(path: str) -> tuple:
    with open(path, 'rb') as f:
        return decode(f.read())
