"""A minimal PNG decoder for loading real test images as JPEG encoder input.

This is I/O plumbing, not part of the codec under test: the PNG *filter*
reconstruction (the actual PNG-specific algorithm -- Sub/Up/Average/Paeth
predictors) is hand-written here, but the DEFLATE decompression itself
uses the stdlib `zlib` module. That's fine because zlib's LZ77+Huffman
never appears anywhere on Spectral's own JPEG encode/decode path -- it
only exists here to get pixels *into* the codec under test, the same way
`bmp.py`'s reader does with zero compression at all.

Supports 8-bit, non-interlaced grayscale/RGB/RGBA/palette PNGs, which
covers every PNG this repo's own from-scratch encoders (and ordinary
screenshots/photos exported as PNG) produce.
"""
import struct
import zlib

from .colorspace import Image

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != _PNG_SIG:
        raise ValueError("not a PNG file")

    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    palette = None
    n = len(data)
    while pos < n:
        if pos + 8 > n:
            raise ValueError("truncated PNG (chunk header)")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        pos += 8 + length + 4  # skip CRC
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", cdata
            )
            if interlace != 0:
                raise ValueError("interlaced PNGs are not supported")
        elif ctype == b"PLTE":
            palette = cdata
        elif ctype == b"IDAT":
            idat += cdata
        elif ctype == b"IEND":
            break

    if width is None:
        raise ValueError("PNG missing IHDR chunk")
    if bit_depth != 8:
        raise ValueError(f"unsupported PNG bit depth {bit_depth} (only 8-bit supported)")

    channels_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in channels_by_type:
        raise ValueError(f"unsupported PNG color type {color_type}")
    channels = channels_by_type[color_type]

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out_rows = []
    prev = bytes(stride)
    pos = 0
    for _y in range(height):
        filt = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        if filt == 0:
            pass
        elif filt == 1:  # Sub
            for i in range(channels, stride):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif filt == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif filt == 3:  # Average
            for i in range(stride):
                a = row[i - channels] if i >= channels else 0
                bpix = prev[i]
                row[i] = (row[i] + ((a + bpix) // 2)) & 0xFF
        elif filt == 4:  # Paeth
            for i in range(stride):
                a = row[i - channels] if i >= channels else 0
                bpix = prev[i]
                c = prev[i - channels] if i >= channels else 0
                row[i] = (row[i] + _paeth(a, bpix, c)) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter type {filt}")
        out_rows.append(bytes(row))
        prev = row

    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)
    for y, row in enumerate(out_rows):
        base = y * width
        if color_type == 0:  # grayscale
            for x in range(width):
                v = row[x]
                r[base + x] = g[base + x] = b[base + x] = v
        elif color_type == 2:  # RGB
            for x in range(width):
                o = x * 3
                r[base + x], g[base + x], b[base + x] = row[o], row[o + 1], row[o + 2]
        elif color_type == 3:  # palette
            for x in range(width):
                idx = row[x] * 3
                r[base + x] = palette[idx]
                g[base + x] = palette[idx + 1]
                b[base + x] = palette[idx + 2]
        elif color_type == 4:  # gray+alpha (alpha ignored: flatten on white)
            for x in range(width):
                o = x * 2
                v, a = row[o], row[o + 1]
                blend = (v * a + 255 * (255 - a)) // 255
                r[base + x] = g[base + x] = b[base + x] = blend
        elif color_type == 6:  # RGBA (alpha ignored: flatten on white)
            for x in range(width):
                o = x * 4
                rr, gg, bb, a = row[o], row[o + 1], row[o + 2], row[o + 3]
                r[base + x] = (rr * a + 255 * (255 - a)) // 255
                g[base + x] = (gg * a + 255 * (255 - a)) // 255
                b[base + x] = (bb * a + 255 * (255 - a)) // 255

    return Image(width, height, r, g, b)
