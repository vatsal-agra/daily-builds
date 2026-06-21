"""Hand-rolled PNG encoder using only Python stdlib (zlib for deflate, CRC-32).

Writes 24-bit truecolor PNG files without any imaging library.
Format reference: https://www.w3.org/TR/PNG/
"""
import struct
import zlib


_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _chunk(name: bytes, data: bytes) -> bytes:
    """Build a PNG chunk: length(4) + type(4) + data + CRC(4)."""
    length = struct.pack('>I', len(data))
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return length + name + data + struct.pack('>I', crc)


def write_png(image, path):
    """Write a 2-D list of Vec3 colours to a PNG file at `path`.

    `image` is indexed as image[y][x], y=0 at top.
    """
    height = len(image)
    width  = len(image[0]) if height else 0

    # IHDR
    ihdr_data = struct.pack('>IIBBBBB', width, height,
                            8,   # bit depth
                            2,   # colour type: RGB truecolor
                            0,   # compression (deflate)
                            0,   # filter method
                            0)   # interlace: none
    ihdr = _chunk(b'IHDR', ihdr_data)

    # Build raw scanlines with Sub filter (filter byte = 1)
    # Sub filter: each byte encoded as (raw - left) mod 256
    # This improves compression for photographic content.
    raw = bytearray()
    for y in range(height):
        raw.append(1)  # Sub filter byte
        prev_r, prev_g, prev_b = 0, 0, 0
        for x in range(width):
            r, g, b = image[y][x].to_rgb8()
            raw.append((r - prev_r) & 0xFF)
            raw.append((g - prev_g) & 0xFF)
            raw.append((b - prev_b) & 0xFF)
            prev_r, prev_g, prev_b = r, g, b

    compressed = zlib.compress(bytes(raw), level=6)
    idat = _chunk(b'IDAT', compressed)

    iend = _chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(_PNG_SIGNATURE)
        f.write(ihdr)
        f.write(idat)
        f.write(iend)


def image_to_ppm(image, path):
    """Write image as PPM (simpler format, no compression)."""
    height = len(image)
    width  = len(image[0]) if height else 0
    lines = [f"P3\n{width} {height}\n255\n"]
    for row in image:
        for px in row:
            r, g, b = px.to_rgb8()
            lines.append(f"{r} {g} {b}\n")
    with open(path, 'w') as f:
        f.writelines(lines)
