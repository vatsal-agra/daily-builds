"""A trivial uncompressed 24-bit BMP reader/writer.

BMP with no compression is the simplest possible real pixel format: a
fixed header plus bottom-up rows of BGR bytes, padded to a 4-byte
boundary. It gives this codec a ground-truth lossless image format to
encode from and to save decoded output to, with zero compression of its
own to entangle with what we're trying to test.
"""
import struct

from .colorspace import Image


def write_bmp(path, image):
    width, height = image.width, image.height
    row_size = (width * 3 + 3) & ~3
    pixel_data_size = row_size * height
    file_size = 54 + pixel_data_size

    header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    dib = struct.pack(
        "<IiiHHIIiiII",
        40, width, height, 1, 24, 0, pixel_data_size, 2835, 2835, 0, 0,
    )

    body = bytearray(pixel_data_size)
    r, g, b = image.r, image.g, image.b
    for y in range(height):
        src_row = height - 1 - y  # BMP stores rows bottom-up
        dst = y * row_size
        base = src_row * width
        for x in range(width):
            i = base + x
            o = dst + x * 3
            body[o] = b[i]
            body[o + 1] = g[i]
            body[o + 2] = r[i]
        # padding bytes are already zero
    with open(path, "wb") as f:
        f.write(header + dib + bytes(body))


def read_bmp(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 54 or data[0:2] != b"BM":
        raise ValueError("not a BMP file")
    pixel_offset = struct.unpack("<I", data[10:14])[0]
    width, height = struct.unpack("<ii", data[18:26])
    bpp = struct.unpack("<H", data[28:30])[0]
    compression = struct.unpack("<I", data[30:34])[0]
    if compression != 0:
        raise ValueError(f"unsupported BMP compression method {compression}")
    if bpp != 24:
        raise ValueError(f"unsupported BMP bit depth {bpp} (only 24-bit supported)")
    top_down = height < 0
    height = abs(height)
    row_size = (width * 3 + 3) & ~3

    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)
    for y in range(height):
        row_off = pixel_offset + y * row_size
        dst_row = y if top_down else (height - 1 - y)
        base = dst_row * width
        row = data[row_off:row_off + width * 3]
        for x in range(width):
            o = x * 3
            b[base + x] = row[o]
            g[base + x] = row[o + 1]
            r[base + x] = row[o + 2]
    return Image(width, height, r, g, b)
