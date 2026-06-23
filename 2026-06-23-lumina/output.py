"""Image output, tone mapping, and hand-rolled PNG encoder for Lumina.

Tone mapping:
  reinhard(x) = x / (1 + x)            — classic global Reinhard
  aces(x)     = (x*(2.51x+0.03))/(...)  — ACES filmic approximation

PNG encoder:
  Pure Python/stdlib implementation: zlib DEFLATE compression, IHDR/IDAT/IEND
  chunks, CRC-32 checksums. No Pillow, no third-party deps.
"""
import struct
import zlib
import json
import math
from vec3 import Vec3


# ── Tone mapping ──────────────────────────────────────────────────────────────

def _reinhard(c: float) -> float:
    return c / (1.0 + c)


def _aces(c: float) -> float:
    a, b, cc, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return (c * (a * c + b)) / (c * (cc * c + d) + e)


def tone_map(pixels: list, method: str = 'reinhard', exposure: float = 1.0) -> list:
    """Apply tone mapping + gamma correction (γ=2.2) to linear Vec3 pixels.

    Returns a list of (r, g, b) tuples with values in [0, 255].
    """
    fn = _aces if method == 'aces' else _reinhard
    result = []
    for p in pixels:
        r = min(1.0, max(0.0, fn(p.x * exposure)))
        g = min(1.0, max(0.0, fn(p.y * exposure)))
        b = min(1.0, max(0.0, fn(p.z * exposure)))
        # Gamma correction γ=2.2
        r = r ** (1.0 / 2.2)
        g = g ** (1.0 / 2.2)
        b = b ** (1.0 / 2.2)
        result.append((int(r * 255.999), int(g * 255.999), int(b * 255.999)))
    return result


# ── PPM writer ────────────────────────────────────────────────────────────────

def write_ppm(path: str, pixels_8bit: list, width: int, height: int):
    """Write an 8-bit RGB PPM file."""
    with open(path, 'wb') as f:
        f.write(f"P6\n{width} {height}\n255\n".encode())
        for r, g, b in pixels_8bit:
            f.write(bytes([r, g, b]))


# ── PNG encoder ───────────────────────────────────────────────────────────────

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack('>I', len(data))
    crc = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def write_png(path: str, pixels_8bit: list, width: int, height: int,
              metadata: dict = None):
    """Encode and write a PNG file from 8-bit (r,g,b) pixel list.

    Uses stdlib zlib for DEFLATE compression. Implements:
      - PNG signature
      - IHDR chunk (width, height, 8-bit, RGB, deflate, adaptive, interlace=0)
      - tEXt chunk for metadata (optional)
      - IDAT chunk (filtered scanlines, zlib-compressed)
      - IEND chunk
    """
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'

    # IHDR: width, height, bit depth=8, color type=2 (RGB), compress=0,
    #       filter=0, interlace=0
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b'IHDR', ihdr_data)

    # Build raw scanlines (one filter byte per row, then RGB triples)
    # Use filter type 0 (None) for simplicity; zlib handles compression
    raw_rows = []
    idx = 0
    for _j in range(height):
        row_bytes = bytearray(1 + width * 3)
        row_bytes[0] = 0  # filter type: None
        out = 1
        for _i in range(width):
            r, g, b = pixels_8bit[idx]
            row_bytes[out] = r
            row_bytes[out + 1] = g
            row_bytes[out + 2] = b
            out += 3
            idx += 1
        raw_rows.append(bytes(row_bytes))

    raw_data = b''.join(raw_rows)
    compressed = zlib.compress(raw_data, level=6)
    idat = _png_chunk(b'IDAT', compressed)

    # Optional metadata tEXt chunk
    text_chunk = b''
    if metadata:
        text_data = b'Comment\x00' + json.dumps(metadata, indent=2).encode('latin-1',
                                                                            errors='replace')
        text_chunk = _png_chunk(b'tEXt', text_data)

    iend = _png_chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(sig + ihdr + text_chunk + idat + iend)


def decode_png_rgb(path: str):
    """Decode a PNG file to list of (r,g,b) tuples using stdlib zlib.

    Only supports 8-bit RGB PNGs (the subset Lumina produces).
    Used for round-trip verification in tests.
    """
    with open(path, 'rb') as f:
        data = f.read()

    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("Not a PNG file")

    # Parse chunks
    idat_chunks = []
    width = height = None
    pos = 8
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        # Verify CRC
        expected_crc = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])[0]
        actual_crc = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"PNG CRC error in {ctype} chunk")
        pos += 12 + length

        if ctype == b'IHDR':
            width, height = struct.unpack('>II', cdata[:8])
            bit_depth = cdata[8]
            color_type = cdata[9]
            if bit_depth != 8 or color_type != 2:
                raise ValueError("Only 8-bit RGB PNG supported by decoder")
        elif ctype == b'IDAT':
            idat_chunks.append(cdata)
        elif ctype == b'IEND':
            break

    if width is None:
        raise ValueError("No IHDR chunk found")

    raw = zlib.decompress(b''.join(idat_chunks))

    # Reconstruct pixels (filter type 0 only, no other filters needed for
    # what Lumina writes — we write filter type 0 for every row)
    pixels = []
    row_len = 1 + width * 3
    for j in range(height):
        row = raw[j * row_len:(j + 1) * row_len]
        if row[0] != 0:
            raise ValueError(f"Unsupported PNG filter type {row[0]} in row {j}")
        for i in range(width):
            r = row[1 + i * 3]
            g = row[1 + i * 3 + 1]
            b = row[1 + i * 3 + 2]
            pixels.append((r, g, b))
    return pixels, width, height


# ── Render statistics ─────────────────────────────────────────────────────────

def bilateral_denoise(pixels: list, width: int, height: int,
                      sigma_s: float = 1.5, sigma_r: float = 0.3,
                      radius: int = 2) -> list:
    """Simple spatial bilateral filter for denoising low-spp renders.

    Weights each neighbour's contribution by:
      w = exp(-dist²/(2σ_s²)) × exp(-color_diff²/(2σ_r²))

    This preserves edges while averaging away high-frequency Monte Carlo noise.

    Args:
        pixels:  Flat list of linear Vec3 pixels.
        width, height: Image dimensions.
        sigma_s: Spatial standard deviation (pixels).
        sigma_r: Range standard deviation (luminance units).
        radius:  Filter half-size (2 → 5×5 kernel).

    Returns:
        New denoised flat list of Vec3 pixels (same length).
    """
    inv_2ss = 1.0 / (2.0 * sigma_s * sigma_s)
    inv_2sr = 1.0 / (2.0 * sigma_r * sigma_r)

    def idx(row, col):
        return row * width + col

    def lum(p):
        return 0.2126 * p.x + 0.7152 * p.y + 0.0722 * p.z

    out = []
    for j in range(height):
        for i in range(width):
            center = pixels[idx(j, i)]
            lc = lum(center)
            wr = wg = wb = 0.0
            total_w = 0.0
            for dj in range(-radius, radius + 1):
                rr = j + dj
                if rr < 0 or rr >= height:
                    continue
                ds_sq_partial = dj * dj
                for di in range(-radius, radius + 1):
                    cc = i + di
                    if cc < 0 or cc >= width:
                        continue
                    p = pixels[idx(rr, cc)]
                    ds_sq = ds_sq_partial + di * di
                    dr = lum(p) - lc
                    w = math.exp(-ds_sq * inv_2ss - dr * dr * inv_2sr)
                    wr += w * p.x
                    wg += w * p.y
                    wb += w * p.z
                    total_w += w
            if total_w > 0:
                out.append(Vec3(wr / total_w, wg / total_w, wb / total_w))
            else:
                out.append(center)
    return out


def pixel_stats(pixels: list) -> dict:
    """Compute luminance statistics for a list of linear Vec3 pixels."""
    if not pixels:
        return {}
    luminances = [0.2126 * p.x + 0.7152 * p.y + 0.0722 * p.z for p in pixels]
    n = len(luminances)
    mean = sum(luminances) / n
    variance = sum((l - mean) ** 2 for l in luminances) / n
    return {
        'n_pixels': n,
        'mean_luminance': mean,
        'std_luminance': math.sqrt(variance),
        'min_luminance': min(luminances),
        'max_luminance': max(luminances),
    }
