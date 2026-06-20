"""
From-scratch PNG encoder + tonemapping (gamma / ACES / reinhard).
No Pillow, no external deps — only zlib from stdlib.
"""
import zlib
import struct
import math


# ── Tonemapping ───────────────────────────────────────────────────────────────

def gamma_correct(c, gamma=2.2):
    """Apply sRGB-ish gamma correction (linear → display). NaN → 0, inf → 1."""
    if math.isnan(c) or c < 0:
        return 0.0
    if math.isinf(c):
        return 1.0
    return min(1.0, c) ** (1.0 / gamma)


def aces_film(x):
    """ACES filmic tonemapping curve (approximation by Krzysztof Narkowicz)."""
    if math.isnan(x) or x < 0:
        return 0.0
    if math.isinf(x):
        return 1.0
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    result = (x * (a * x + b)) / (x * (c * x + d) + e)
    return max(0.0, min(1.0, result))


def reinhard(x):
    if math.isnan(x) or x < 0:
        return 0.0
    if math.isinf(x):
        return 1.0
    return x / (1.0 + x)


def tonemap(pixels, method='aces', gamma=2.2):
    """
    Convert list of Vec3 linear-HDR pixels to list of (r,g,b) 8-bit tuples.
    method: 'aces' | 'reinhard' | 'gamma' | 'clamp'
    """
    out = []
    for p in pixels:
        if method == 'aces':
            r = aces_film(p.x); g = aces_film(p.y); b = aces_film(p.z)
        elif method == 'reinhard':
            r = reinhard(p.x); g = reinhard(p.y); b = reinhard(p.z)
        elif method == 'clamp':
            r = max(0, min(1, p.x)); g = max(0, min(1, p.y)); b = max(0, min(1, p.z))
        elif method == 'gamma':
            r = p.x; g = p.y; b = p.z   # just gamma-correct raw linear values
        else:
            raise ValueError(f"Unknown tonemap method: {method!r}. "
                             "Choose from: aces, reinhard, clamp, gamma")
        r = gamma_correct(r, gamma)
        g = gamma_correct(g, gamma)
        b = gamma_correct(b, gamma)
        out.append((int(r * 255.999), int(g * 255.999), int(b * 255.999)))
    return out


# ── PNG encoder ───────────────────────────────────────────────────────────────

def _chunk(chunk_type, data):
    c = chunk_type + data
    crc = zlib.crc32(c) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)


def encode_png(width, height, rgb_pixels):
    """
    Encode list of (r,g,b) 8-bit tuples to PNG bytes.
    Pixels are row-major, top-to-bottom.
    """
    # Build raw image data with filter byte 0 (None) per row
    raw_rows = []
    for row in range(height):
        row_start = row * width
        row_pixels = rgb_pixels[row_start:row_start + width]
        row_bytes = bytearray([0])   # filter type: None
        for (r, g, b) in row_pixels:
            row_bytes += bytes([r, g, b])
        raw_rows.append(bytes(row_bytes))

    image_data = zlib.compress(b''.join(raw_rows), level=6)

    png_sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b'IHDR', ihdr_data)
    idat = _chunk(b'IDAT', image_data)
    iend = _chunk(b'IEND', b'')
    return png_sig + ihdr + idat + iend


def save_png(path, width, height, pixels, tonemap_method='aces', gamma=2.2):
    """Tonemap Vec3 HDR pixels and write a PNG file."""
    rgb = tonemap(pixels, method=tonemap_method, gamma=gamma)
    png_bytes = encode_png(width, height, rgb)
    with open(path, 'wb') as f:
        f.write(png_bytes)
    return len(png_bytes)


def save_ppm(path, width, height, pixels, tonemap_method='aces', gamma=2.2):
    """Write a PPM (debug format, no encoding overhead)."""
    rgb = tonemap(pixels, method=tonemap_method, gamma=gamma)
    with open(path, 'w') as f:
        f.write(f"P3\n{width} {height}\n255\n")
        for (r, g, b) in rgb:
            f.write(f"{r} {g} {b}\n")
