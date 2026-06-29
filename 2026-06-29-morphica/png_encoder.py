"""Hand-rolled PNG encoder. No Pillow, no external deps."""
import zlib
import struct


def encode_png(width, height, pixels, mode="RGB"):
    """
    Encode raw pixel data to PNG bytes.

    pixels: flat list/bytes of (r,g,b) tuples or (r,g,b,a) tuples,
            row-major top-to-bottom.
    mode: "RGB" or "RGBA"
    """
    channels = 4 if mode == "RGBA" else 3
    color_type = 6 if channels == 4 else 2

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    # Build raw scanlines with Sub filter (type 1)
    raw = bytearray()
    for y in range(height):
        raw.append(1)  # Sub filter
        row_start = y * width
        prev = [0] * channels
        for x in range(width):
            px = pixels[row_start + x]
            if channels == 3:
                vals = [px[0], px[1], px[2]]
            else:
                vals = [px[0], px[1], px[2], px[3] if len(px) > 3 else 255]
            for ch in range(channels):
                filtered = (vals[ch] - prev[ch]) & 0xFF
                raw.append(filtered)
            prev = vals

    compressed = zlib.compress(bytes(raw), 6)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    return png


def save_png(path, width, height, pixels, mode="RGB"):
    with open(path, "wb") as f:
        f.write(encode_png(width, height, pixels, mode))
