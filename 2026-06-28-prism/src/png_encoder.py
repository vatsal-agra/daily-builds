"""From-scratch PNG encoder (no PIL/Pillow). Outputs 8-bit RGB PNG."""
import struct
import zlib


def _crc32(data): return zlib.crc32(data) & 0xFFFFFFFF


def _chunk(tag, data):
    tag = tag.encode() if isinstance(tag, str) else tag
    length = struct.pack('>I', len(data))
    crc = struct.pack('>I', _crc32(tag + data))
    return length + tag + data + crc


def encode_png(width, height, rgb_bytes):
    """
    Encode raw RGB bytes (len = width*height*3, top-row first, left-to-right)
    into a valid PNG byte string.
    """
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'

    # IHDR
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk('IHDR', ihdr_data)

    # IDAT: apply Sub filter (type 1) row by row
    raw = bytearray()
    row_bytes = width * 3
    for y in range(height):
        raw.append(1)  # filter type = Sub
        row_start = y * row_bytes
        for x in range(row_bytes):
            cur = rgb_bytes[row_start + x]
            prev = rgb_bytes[row_start + x - 3] if x >= 3 else 0
            raw.append((cur - prev) & 0xFF)

    compressed = zlib.compress(bytes(raw), level=6)
    idat = _chunk('IDAT', compressed)

    iend = _chunk('IEND', b'')

    return sig + ihdr + idat + iend


def save_png(path, width, height, rgb_bytes):
    with open(path, 'wb') as f:
        f.write(encode_png(width, height, rgb_bytes))
