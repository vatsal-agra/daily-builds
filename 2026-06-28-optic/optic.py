#!/usr/bin/env python3
"""
Optic — Computer Vision from Scratch
Pure Python 3 stdlib only. No NumPy, no Pillow, no external deps.

Usage: python3 optic.py <command> [args]
Commands: info, edges, corners, morph, components, hough, match, thresh, viz, demo
"""

import argparse
import base64
import colorsys
import json
import math
import os
import struct
import sys
import zlib
from collections import deque

# ═══════════════════════════════════════════════════════════════════════════════
# PNG I/O
# ═══════════════════════════════════════════════════════════════════════════════

_PNG_SIG = b'\x89PNG\r\n\x1a\n'


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _make_chunk(ctype: bytes, data: bytes) -> bytes:
    body = ctype + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', _crc32(body))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: str) -> 'Image':
    with open(path, 'rb') as f:
        return decode_png(f.read())


def decode_png(data: bytes) -> 'Image':
    if data[:8] != _PNG_SIG:
        raise ValueError("Not a PNG file (bad signature)")

    pos = 8
    idat_parts = []
    width = height = bit_depth = color_type = 0
    interlace = 0

    while pos < len(data):
        if pos + 12 > len(data):
            break
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        stored_crc = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])[0]
        if _crc32(ctype + cdata) != stored_crc:
            raise ValueError(f"CRC mismatch in chunk {ctype!r}")
        pos += 12 + length

        if ctype == b'IHDR':
            width, height = struct.unpack('>II', cdata[:8])
            bit_depth, color_type = cdata[8], cdata[9]
            interlace = cdata[12]
            if interlace != 0:
                raise ValueError("Interlaced PNG not supported")
        elif ctype == b'IDAT':
            idat_parts.append(cdata)
        elif ctype == b'IEND':
            break

    # color_type → (n_channels, mode)
    ct_map = {0: (1, 'L'), 2: (3, 'RGB'), 4: (2, 'LA'), 6: (4, 'RGBA')}
    if color_type not in ct_map:
        raise ValueError(f"Unsupported PNG color type {color_type}")
    n_ch, mode = ct_map[color_type]

    if bit_depth not in (8, 16):
        raise ValueError(f"Unsupported bit depth {bit_depth}")
    bps = bit_depth // 8  # bytes per sample per channel

    raw = zlib.decompress(b''.join(idat_parts))
    row_bytes = width * n_ch * bps

    # Reconstruct filtered scanlines
    img = Image(width, height, mode)
    prev = bytearray(row_bytes)
    p = 0
    stride = n_ch * bps

    for r in range(height):
        ft = raw[p]; p += 1
        row = bytearray(raw[p:p + row_bytes]); p += row_bytes

        if ft == 1:    # Sub
            for i in range(stride, len(row)):
                row[i] = (row[i] + row[i - stride]) & 0xFF
        elif ft == 2:  # Up
            for i in range(len(row)):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(len(row)):
                a = row[i - stride] if i >= stride else 0
                row[i] = (row[i] + (a + prev[i]) // 2) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(len(row)):
                a = row[i - stride] if i >= stride else 0
                b = prev[i]
                c = prev[i - stride] if i >= stride else 0
                row[i] = (row[i] + _paeth(a, b, c)) & 0xFF
        # ft == 0: None — no action

        base = r * width
        if bps == 1:
            for c_idx in range(width):
                off = c_idx * n_ch
                for ch in range(n_ch):
                    img.planes[ch][base + c_idx] = row[off + ch] / 255.0
        else:
            for c_idx in range(width):
                off = c_idx * n_ch * 2
                for ch in range(n_ch):
                    hi = row[off + ch * 2]; lo = row[off + ch * 2 + 1]
                    img.planes[ch][base + c_idx] = (hi * 256 + lo) / 65535.0

        prev = row

    return img


def write_png(img: 'Image', path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(encode_png(img))


def encode_png(img: 'Image') -> bytes:
    w, h = img.width, img.height
    ct_map = {'L': (0, 1), 'RGB': (2, 3), 'LA': (4, 2), 'RGBA': (6, 4)}
    color_type, n_ch = ct_map[img.mode]

    ihdr = struct.pack('>IIBBBBB', w, h, 8, color_type, 0, 0, 0)
    stride = n_ch
    rows = []

    for r in range(h):
        raw = bytearray(w * stride)
        for c in range(w):
            off = c * stride
            base = r * w + c
            for ch in range(n_ch):
                v = img.planes[ch][base]
                raw[off + ch] = max(0, min(255, int(v * 255.0 + 0.5)))
        # Apply Sub filter (type 1)
        filt = bytearray(w * stride)
        for i in range(len(raw)):
            a = raw[i - stride] if i >= stride else 0
            filt[i] = (raw[i] - a) & 0xFF
        rows.append(bytes([1]) + bytes(filt))

    compressed = zlib.compress(b''.join(rows), level=6)
    return (
        _PNG_SIG
        + _make_chunk(b'IHDR', ihdr)
        + _make_chunk(b'IDAT', compressed)
        + _make_chunk(b'IEND', b'')
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Image class
# ═══════════════════════════════════════════════════════════════════════════════

class Image:
    """
    planes[channel][row * width + col] = float in [0.0, 1.0].
    Modes: 'L' (grayscale), 'RGB', 'RGBA', 'LA'.
    """

    _MODE_CHANNELS = {'L': 1, 'RGB': 3, 'RGBA': 4, 'LA': 2}

    def __init__(self, width: int, height: int, mode: str = 'RGB', fill: float = 0.0):
        self.width = width
        self.height = height
        self.mode = mode
        n = width * height
        self.planes = [[fill] * n for _ in range(self._MODE_CHANNELS[mode])]

    @property
    def n_channels(self) -> int:
        return len(self.planes)

    def copy(self) -> 'Image':
        out = Image.__new__(Image)
        out.width = self.width
        out.height = self.height
        out.mode = self.mode
        out.planes = [list(p) for p in self.planes]
        return out

    def get(self, row: int, col: int, ch: int = 0) -> float:
        return self.planes[ch][row * self.width + col]

    def set(self, row: int, col: int, ch: int, val: float):
        self.planes[ch][row * self.width + col] = val

    # ─── photometric ops ───────────────────────────────────────────────────────

    def grayscale(self) -> 'Image':
        if self.mode == 'L':
            return self.copy()
        W, H, n = self.width, self.height, self.width * self.height
        out = Image(W, H, 'L')
        if self.mode == 'RGB':
            r, g, b = self.planes
            out.planes[0] = [0.2126 * r[i] + 0.7152 * g[i] + 0.0722 * b[i] for i in range(n)]
        elif self.mode == 'RGBA':
            r, g, b = self.planes[0], self.planes[1], self.planes[2]
            out.planes[0] = [0.2126 * r[i] + 0.7152 * g[i] + 0.0722 * b[i] for i in range(n)]
        elif self.mode == 'LA':
            out.planes[0] = list(self.planes[0])
        return out

    def to_rgb(self) -> 'Image':
        if self.mode == 'RGB':
            return self.copy()
        W, H = self.width, self.height
        out = Image(W, H, 'RGB')
        if self.mode == 'L':
            ch = list(self.planes[0])
            out.planes = [ch, list(ch), list(ch)]
        elif self.mode == 'RGBA':
            out.planes = [list(self.planes[0]), list(self.planes[1]), list(self.planes[2])]
        elif self.mode == 'LA':
            ch = list(self.planes[0])
            out.planes = [ch, list(ch), list(ch)]
        return out

    def to_l(self) -> 'Image':
        return self.grayscale()

    def adjust_brightness(self, factor: float) -> 'Image':
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            out.planes[ch] = [min(1.0, max(0.0, v * factor)) for v in self.planes[ch]]
        return out

    def adjust_contrast(self, factor: float) -> 'Image':
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            out.planes[ch] = [min(1.0, max(0.0, (v - 0.5) * factor + 0.5)) for v in self.planes[ch]]
        return out

    def adjust_gamma(self, gamma: float) -> 'Image':
        inv = 1.0 / max(1e-8, gamma)
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            out.planes[ch] = [max(0.0, v) ** inv for v in self.planes[ch]]
        return out

    def normalize(self) -> 'Image':
        """Rescale each channel to [0,1]."""
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            p = self.planes[ch]
            mn, mx = min(p), max(p)
            rng = mx - mn
            if rng > 1e-12:
                out.planes[ch] = [(v - mn) / rng for v in p]
            else:
                out.planes[ch] = [0.0] * len(p)
        return out

    def clamp(self) -> 'Image':
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            out.planes[ch] = [min(1.0, max(0.0, v)) for v in self.planes[ch]]
        return out

    # ─── geometric ops ─────────────────────────────────────────────────────────

    def flip_h(self) -> 'Image':
        W, H = self.width, self.height
        out = Image(W, H, self.mode)
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(H):
                for c in range(W):
                    dst[r * W + (W - 1 - c)] = src[r * W + c]
        return out

    def flip_v(self) -> 'Image':
        W, H = self.width, self.height
        out = Image(W, H, self.mode)
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(H):
                dst[(H - 1 - r) * W:(H - r) * W] = src[r * W:(r + 1) * W]
        return out

    def crop(self, x: int, y: int, cw: int, ch_: int) -> 'Image':
        out = Image(cw, ch_, self.mode)
        W = self.width
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(ch_):
                for c in range(cw):
                    sr = y + r; sc = x + c
                    if 0 <= sr < self.height and 0 <= sc < W:
                        dst[r * cw + c] = src[sr * W + sc]
        return out

    def pad(self, top: int, bottom: int, left: int, right: int, fill: float = 0.0) -> 'Image':
        nw = self.width + left + right
        nh = self.height + top + bottom
        out = Image(nw, nh, self.mode, fill=fill)
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(self.height):
                for c in range(self.width):
                    dst[(top + r) * nw + (left + c)] = src[r * self.width + c]
        return out

    def resize_nearest(self, new_w: int, new_h: int) -> 'Image':
        out = Image(new_w, new_h, self.mode)
        sx = self.width / new_w; sy = self.height / new_h
        W, H = self.width, self.height
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(new_h):
                sr = min(int(r * sy), H - 1)
                for c in range(new_w):
                    sc = min(int(c * sx), W - 1)
                    dst[r * new_w + c] = src[sr * W + sc]
        return out

    def resize_bilinear(self, new_w: int, new_h: int) -> 'Image':
        out = Image(new_w, new_h, self.mode)
        sx = self.width / new_w; sy = self.height / new_h
        W, H = self.width, self.height
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(new_h):
                fy = (r + 0.5) * sy - 0.5
                y0 = max(0, min(H - 1, int(fy)))
                y1 = min(H - 1, y0 + 1)
                dy = fy - y0
                for c in range(new_w):
                    fx = (c + 0.5) * sx - 0.5
                    x0 = max(0, min(W - 1, int(fx)))
                    x1 = min(W - 1, x0 + 1)
                    dx = fx - x0
                    dst[r * new_w + c] = (
                        src[y0 * W + x0] * (1 - dx) * (1 - dy)
                        + src[y0 * W + x1] * dx * (1 - dy)
                        + src[y1 * W + x0] * (1 - dx) * dy
                        + src[y1 * W + x1] * dx * dy
                    )
        return out

    def rotate(self, degrees: float, fill: float = 0.0) -> 'Image':
        rad = math.radians(degrees)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        W, H = self.width, self.height
        cx, cy = W / 2.0, H / 2.0
        out = Image(W, H, self.mode, fill=fill)
        for ch in range(self.n_channels):
            src = self.planes[ch]; dst = out.planes[ch]
            for r in range(H):
                for c in range(W):
                    dx = c - cx; dy = r - cy
                    sx = cos_a * dx + sin_a * dy + cx
                    sy = -sin_a * dx + cos_a * dy + cy
                    if 0 <= sx < W - 1 and 0 <= sy < H - 1:
                        x0 = int(sx); y0 = int(sy)
                        fx = sx - x0; fy = sy - y0
                        dst[r * W + c] = (
                            src[y0 * W + x0] * (1 - fx) * (1 - fy)
                            + src[y0 * W + x0 + 1] * fx * (1 - fy)
                            + src[(y0 + 1) * W + x0] * (1 - fx) * fy
                            + src[(y0 + 1) * W + x0 + 1] * fx * fy
                        )
                    else:
                        dst[r * W + c] = fill
        return out

    def split_channels(self) -> list:
        result = []
        for ch in range(self.n_channels):
            img = Image(self.width, self.height, 'L')
            img.planes[0] = list(self.planes[ch])
            result.append(img)
        return result

    @staticmethod
    def merge_channels(channels: list, mode: str) -> 'Image':
        w, h = channels[0].width, channels[0].height
        out = Image(w, h, mode)
        for ch, img in enumerate(channels):
            out.planes[ch] = list(img.planes[0])
        return out

    def blend(self, other: 'Image', alpha: float) -> 'Image':
        n = self.width * self.height
        out = Image(self.width, self.height, self.mode)
        for ch in range(self.n_channels):
            a = self.planes[ch]; b = other.planes[ch]
            out.planes[ch] = [a[i] * (1 - alpha) + b[i] * alpha for i in range(n)]
        return out


# ═══════════════════════════════════════════════════════════════════════════════
# Convolution & edge detection (R2)
# ═══════════════════════════════════════════════════════════════════════════════

def _clamp_idx(i: int, n: int) -> int:
    return max(0, min(n - 1, i))


def convolve2d(img: Image, kernel: list) -> Image:
    """2D convolution on a single-channel Image with clamped borders."""
    assert img.mode == 'L', "convolve2d requires 'L' mode"
    kh = len(kernel); kw = len(kernel[0])
    ph = kh // 2; pw = kw // 2
    W, H = img.width, img.height
    src = img.planes[0]
    out = Image(W, H, 'L')
    dst = out.planes[0]
    # Flatten kernel for speed
    flat_k = [kernel[ky][kx] for ky in range(kh) for kx in range(kw)]
    for r in range(H):
        for c in range(W):
            acc = 0.0
            ki = 0
            for ky in range(kh):
                sr = _clamp_idx(r + ky - ph, H)
                sr_off = sr * W
                for kx in range(kw):
                    sc = _clamp_idx(c + kx - pw, W)
                    acc += src[sr_off + sc] * flat_k[ki]
                    ki += 1
            dst[r * W + c] = acc
    return out


def _convolve1d_h(img: Image, kernel: list) -> Image:
    k = len(kernel); pad = k // 2
    W, H = img.width, img.height
    src = img.planes[0]
    out = Image(W, H, 'L')
    dst = out.planes[0]
    for r in range(H):
        roff = r * W
        for c in range(W):
            acc = 0.0
            for i in range(k):
                sc = _clamp_idx(c + i - pad, W)
                acc += src[roff + sc] * kernel[i]
            dst[roff + c] = acc
    return out


def _convolve1d_v(img: Image, kernel: list) -> Image:
    k = len(kernel); pad = k // 2
    W, H = img.width, img.height
    src = img.planes[0]
    out = Image(W, H, 'L')
    dst = out.planes[0]
    for r in range(H):
        for c in range(W):
            acc = 0.0
            for i in range(k):
                sr = _clamp_idx(r + i - pad, H)
                acc += src[sr * W + c] * kernel[i]
            dst[r * W + c] = acc
    return out


def _gaussian_kernel_1d(sigma: float) -> list:
    radius = max(1, int(math.ceil(3.0 * sigma)))
    vals = [math.exp(-x * x / (2.0 * sigma * sigma)) for x in range(-radius, radius + 1)]
    s = sum(vals)
    return [v / s for v in vals]


def gaussian_blur(img: Image, sigma: float) -> Image:
    """Gaussian blur via separable 1D passes. Works on any mode."""
    k = _gaussian_kernel_1d(sigma)
    if img.mode == 'L':
        return _convolve1d_v(_convolve1d_h(img, k), k)
    channels = img.split_channels()
    blurred = [_convolve1d_v(_convolve1d_h(ch, k), k) for ch in channels]
    return Image.merge_channels(blurred, img.mode)


def sobel(img: Image) -> tuple:
    """Compute Sobel gradients. Returns (Gx, Gy, magnitude, direction) all as 'L' Images."""
    if img.mode != 'L':
        img = img.grayscale()
    Kx = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
    Ky = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
    gx = convolve2d(img, Kx)
    gy = convolve2d(img, Ky)
    W, H, n = img.width, img.height, img.width * img.height
    mag = Image(W, H, 'L')
    dirn = Image(W, H, 'L')
    gxp, gyp, mp, dp = gx.planes[0], gy.planes[0], mag.planes[0], dirn.planes[0]
    for i in range(n):
        mp[i] = math.hypot(gxp[i], gyp[i])
        dp[i] = math.atan2(gyp[i], gxp[i])
    return gx, gy, mag, dirn


def prewitt(img: Image) -> tuple:
    """Prewitt gradient operator. Returns (Gx, Gy, magnitude, direction)."""
    if img.mode != 'L':
        img = img.grayscale()
    Kx = [[-1, 0, 1], [-1, 0, 1], [-1, 0, 1]]
    Ky = [[-1, -1, -1], [0, 0, 0], [1, 1, 1]]
    gx = convolve2d(img, Kx)
    gy = convolve2d(img, Ky)
    W, H, n = img.width, img.height, img.width * img.height
    mag = Image(W, H, 'L')
    dirn = Image(W, H, 'L')
    for i in range(n):
        mag.planes[0][i] = math.hypot(gx.planes[0][i], gy.planes[0][i])
        dirn.planes[0][i] = math.atan2(gy.planes[0][i], gx.planes[0][i])
    return gx, gy, mag, dirn


def scharr(img: Image) -> tuple:
    """Scharr gradient operator (better rotation invariance). Returns (Gx, Gy, magnitude, direction)."""
    if img.mode != 'L':
        img = img.grayscale()
    Kx = [[-3, 0, 3], [-10, 0, 10], [-3, 0, 3]]
    Ky = [[-3, -10, -3], [0, 0, 0], [3, 10, 3]]
    gx = convolve2d(img, Kx)
    gy = convolve2d(img, Ky)
    W, H, n = img.width, img.height, img.width * img.height
    mag = Image(W, H, 'L')
    dirn = Image(W, H, 'L')
    for i in range(n):
        mag.planes[0][i] = math.hypot(gx.planes[0][i], gy.planes[0][i])
        dirn.planes[0][i] = math.atan2(gy.planes[0][i], gx.planes[0][i])
    return gx, gy, mag, dirn


def canny(img: Image, sigma: float = 1.4, low: float = 0.10, high: float = 0.20) -> Image:
    """
    Full Canny edge detector:
      1. Gaussian blur
      2. Sobel gradient magnitude + direction
      3. Non-maximum suppression (sub-pixel along gradient direction)
      4. Double threshold + hysteresis BFS
    """
    if img.mode != 'L':
        img = img.grayscale()

    blurred = gaussian_blur(img, sigma)
    gx, gy, mag, dirn = sobel(blurred)

    W, H = img.width, img.height
    mag_p = mag.planes[0]
    dir_p = dirn.planes[0]

    max_mag = max(mag_p) if mag_p else 1.0
    if max_mag < 1e-12:
        return Image(W, H, 'L')
    scale = 1.0 / max_mag
    norm = [v * scale for v in mag_p]

    # Non-maximum suppression
    STRONG, WEAK = 1.0, 0.5
    res = Image(W, H, 'L')
    rp = res.planes[0]

    for r in range(1, H - 1):
        for c in range(1, W - 1):
            i = r * W + c
            m = norm[i]
            angle = math.degrees(dir_p[i]) % 180

            if angle < 22.5 or angle >= 157.5:      # horizontal edge → compare left/right
                n1 = norm[i + 1]; n2 = norm[i - 1]
            elif angle < 67.5:                       # 45°
                n1 = norm[(r - 1) * W + c + 1]; n2 = norm[(r + 1) * W + c - 1]
            elif angle < 112.5:                      # vertical edge → compare top/bottom
                n1 = norm[(r - 1) * W + c]; n2 = norm[(r + 1) * W + c]
            else:                                    # 135°
                n1 = norm[(r - 1) * W + c - 1]; n2 = norm[(r + 1) * W + c + 1]

            if m < n1 or m < n2:
                continue
            if m >= high:
                rp[i] = STRONG
            elif m >= low:
                rp[i] = WEAK

    # Hysteresis BFS: grow strong edges into adjacent weak ones
    visited = bytearray(W * H)
    queue = deque()
    for r in range(1, H - 1):
        for c in range(1, W - 1):
            i = r * W + c
            if rp[i] == STRONG and not visited[i]:
                visited[i] = 1
                queue.append((r, c))

    while queue:
        r, c = queue.popleft()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W:
                    ni = nr * W + nc
                    if not visited[ni] and rp[ni] == WEAK:
                        visited[ni] = 1
                        rp[ni] = STRONG
                        queue.append((nr, nc))

    # Kill remaining weak pixels
    for i in range(W * H):
        if rp[i] == WEAK:
            rp[i] = 0.0

    return res


def bilateral_filter(img: Image, sigma_s: float = 2.0, sigma_r: float = 0.15) -> Image:
    """
    Bilateral filter — edge-preserving smoothing (stretch feature S4).
    Each output pixel is a weighted average of neighbors, where weights combine:
      - spatial Gaussian (sigma_s): nearby pixels weighted more
      - range Gaussian (sigma_r): similar-intensity pixels weighted more
    Edges are preserved because pixels across an edge have large intensity differences
    → low range weight → they don't blur together.
    sigma_s: spatial spread (pixels); sigma_r: intensity range spread (0–1 scale).
    """
    radius = max(1, int(math.ceil(2.5 * sigma_s)))
    s2 = 2.0 * sigma_s * sigma_s
    r2 = 2.0 * sigma_r * sigma_r

    # Precompute spatial weights for the window
    spatial = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            spatial.append((dy, dx, math.exp(-(dy * dy + dx * dx) / s2)))

    if img.mode == 'L':
        channels = [img]
    else:
        channels = img.split_channels()

    out_channels = []
    for ch_img in channels:
        W, H = ch_img.width, ch_img.height
        src = ch_img.planes[0]
        out = Image(W, H, 'L')
        dst = out.planes[0]
        for r in range(H):
            for c in range(W):
                p = src[r * W + c]
                acc = 0.0; wsum = 0.0
                for dy, dx, ws in spatial:
                    nr = _clamp_idx(r + dy, H)
                    nc = _clamp_idx(c + dx, W)
                    q = src[nr * W + nc]
                    diff = p - q
                    wr = math.exp(-diff * diff / r2)
                    w = ws * wr
                    acc += q * w
                    wsum += w
                dst[r * W + c] = acc / wsum if wsum > 1e-12 else p
        out_channels.append(out)

    if img.mode == 'L':
        return out_channels[0]
    return Image.merge_channels(out_channels, img.mode)


# ═══════════════════════════════════════════════════════════════════════════════
# Feature detection: Harris + FAST (R3)
# ═══════════════════════════════════════════════════════════════════════════════

def harris_corners(img: Image, k: float = 0.04, sigma: float = 1.0,
                   win_sigma: float = 1.5, threshold: float = 0.01,
                   nms_radius: int = 5, top_n: int = 100) -> list:
    """
    Harris corner detector.
    Returns list of (row, col, response) sorted by response descending.
    """
    if img.mode != 'L':
        img = img.grayscale()

    gx, gy, _, _ = sobel(img)
    W, H, n = img.width, img.height, img.width * img.height

    gxp, gyp = gx.planes[0], gy.planes[0]
    Ixx = Image(W, H, 'L'); Iyy = Image(W, H, 'L'); Ixy = Image(W, H, 'L')
    Ixx.planes[0] = [gxp[i] * gxp[i] for i in range(n)]
    Iyy.planes[0] = [gyp[i] * gyp[i] for i in range(n)]
    Ixy.planes[0] = [gxp[i] * gyp[i] for i in range(n)]

    Ixx_s = gaussian_blur(Ixx, win_sigma)
    Iyy_s = gaussian_blur(Iyy, win_sigma)
    Ixy_s = gaussian_blur(Ixy, win_sigma)

    ixx, iyy, ixy = Ixx_s.planes[0], Iyy_s.planes[0], Ixy_s.planes[0]
    R = [ixx[i] * iyy[i] - ixy[i] * ixy[i] - k * (ixx[i] + iyy[i]) ** 2 for i in range(n)]

    max_R = max(R)
    if max_R <= 0:
        return []

    thresh_abs = threshold * max_R

    # Collect candidates and do NMS
    nr = nms_radius
    candidates = []
    for r in range(nr, H - nr):
        for c in range(nr, W - nr):
            v = R[r * W + c]
            if v < thresh_abs:
                continue
            is_max = True
            for dr in range(-nr, nr + 1):
                for dc in range(-nr, nr + 1):
                    if dr == 0 and dc == 0:
                        continue
                    if R[(r + dr) * W + (c + dc)] > v:
                        is_max = False
                        break
                if not is_max:
                    break
            if is_max:
                candidates.append((r, c, v / max_R))

    candidates.sort(key=lambda x: -x[2])
    return candidates[:top_n]


def fast_corners(img: Image, threshold: float = 0.05, n_arc: int = 9,
                 nms_radius: int = 3, top_n: int = 200) -> list:
    """
    FAST corner detector (Features from Accelerated Segment Test).
    Returns list of (row, col, score) sorted by score descending.
    """
    if img.mode != 'L':
        img = img.grayscale()

    W, H = img.width, img.height
    src = img.planes[0]

    # Bresenham circle of radius 3 (16 pixels)
    CIRCLE = [
        (-3, 0), (-3, 1), (-2, 2), (-1, 3),
        (0, 3),  (1, 3),  (2, 2),  (3, 1),
        (3, 0),  (3, -1), (2, -2), (1, -3),
        (0, -3), (-1, -3), (-2, -2), (-3, -1),
    ]
    N = len(CIRCLE)
    # Precompute offsets into flat array
    circle_off = [dr * W + dc for dr, dc in CIRCLE]

    def max_arc(flags):
        n = len(flags)
        best = cur = 0
        for _ in range(2):
            for f in flags:
                cur = cur + 1 if f else 0
                best = max(best, cur)
        return min(best, n)

    raw = []
    for r in range(3, H - 3):
        roff = r * W
        for c in range(3, W - 3):
            p = src[roff + c]
            lo = p - threshold
            hi = p + threshold

            # Quick test: pixels at 0, 4, 8, 12
            def pv(k):
                dr, dc = CIRCLE[k]
                return src[(r + dr) * W + (c + dc)]

            n_bright = sum(1 for k in (0, 4, 8, 12) if pv(k) > hi)
            n_dark   = sum(1 for k in (0, 4, 8, 12) if pv(k) < lo)
            if n_bright < 3 and n_dark < 3:
                continue

            vals = [src[roff + c + circle_off[k]] for k in range(N)]
            is_b = [v > hi for v in vals]
            is_d = [v < lo for v in vals]

            if max_arc(is_b) >= n_arc or max_arc(is_d) >= n_arc:
                score = max(vals) - min(vals)
                raw.append((r, c, score))

    # NMS
    score_map = {(r, c): s for r, c, s in raw}
    nr = nms_radius
    suppressed = []
    for r, c, s in raw:
        is_max = all(
            score_map.get((r + dr, c + dc), 0) <= s
            for dr in range(-nr, nr + 1)
            for dc in range(-nr, nr + 1)
            if not (dr == 0 and dc == 0)
        )
        if is_max:
            suppressed.append((r, c, s))

    suppressed.sort(key=lambda x: -x[2])
    return suppressed[:top_n]


# ═══════════════════════════════════════════════════════════════════════════════
# Morphological operations + Connected Components (R4)
# ═══════════════════════════════════════════════════════════════════════════════

def make_se(shape: str = 'cross', size: int = 3) -> list:
    """
    Build a structuring element as a list of (dr, dc) offsets.
    shape: 'cross', 'square', 'disk'.  size: odd integer.
    """
    r = size // 2
    if shape == 'cross':
        offsets = [(0, dc) for dc in range(-r, r + 1)]
        offsets += [(dr, 0) for dr in range(-r, r + 1) if dr != 0]
    elif shape == 'square':
        offsets = [(dr, dc) for dr in range(-r, r + 1) for dc in range(-r, r + 1)]
    elif shape == 'disk':
        offsets = [(dr, dc) for dr in range(-r, r + 1) for dc in range(-r, r + 1)
                   if dr * dr + dc * dc <= r * r]
    else:
        raise ValueError(f"Unknown SE shape '{shape}'. Choose: cross, square, disk")
    return offsets


def dilate(img: Image, se: list) -> Image:
    """Binary dilation. img should be 'L' with values 0 or 1."""
    assert img.mode == 'L'
    W, H = img.width, img.height
    src = img.planes[0]
    out = Image(W, H, 'L')
    dst = out.planes[0]
    for r in range(H):
        for c in range(W):
            for dr, dc in se:
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W and src[nr * W + nc] > 0.5:
                    dst[r * W + c] = 1.0
                    break
    return out


def erode(img: Image, se: list) -> Image:
    """Binary erosion."""
    assert img.mode == 'L'
    W, H = img.width, img.height
    src = img.planes[0]
    out = Image(W, H, 'L')
    dst = out.planes[0]
    for r in range(H):
        for c in range(W):
            ok = True
            for dr, dc in se:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < H and 0 <= nc < W and src[nr * W + nc] > 0.5):
                    ok = False
                    break
            if ok:
                dst[r * W + c] = 1.0
    return out


def opening(img: Image, se: list) -> Image:
    return dilate(erode(img, se), se)


def closing(img: Image, se: list) -> Image:
    return erode(dilate(img, se), se)


def morph_gradient(img: Image, se: list) -> Image:
    """Morphological gradient = dilation - erosion."""
    d, e = dilate(img, se), erode(img, se)
    n = img.width * img.height
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [max(0.0, d.planes[0][i] - e.planes[0][i]) for i in range(n)]
    return out


def top_hat(img: Image, se: list) -> Image:
    """White top-hat = img - opening(img)."""
    o = opening(img, se)
    n = img.width * img.height
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [max(0.0, img.planes[0][i] - o.planes[0][i]) for i in range(n)]
    return out


def black_hat(img: Image, se: list) -> Image:
    """Black top-hat = closing(img) - img."""
    c = closing(img, se)
    n = img.width * img.height
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [max(0.0, c.planes[0][i] - img.planes[0][i]) for i in range(n)]
    return out


def hit_or_miss(img: Image, se_hit: list, se_miss: list) -> Image:
    """Hit-or-miss transform: pixels where SE_hit fits foreground and SE_miss fits background."""
    assert img.mode == 'L'
    n = img.width * img.height
    comp = Image(img.width, img.height, 'L')
    comp.planes[0] = [1.0 - v for v in img.planes[0]]
    h = erode(img, se_hit)
    m = erode(comp, se_miss)
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [1.0 if h.planes[0][i] > 0.5 and m.planes[0][i] > 0.5 else 0.0 for i in range(n)]
    return out


def connected_components(img: Image, connectivity: int = 8):
    """
    Two-pass connected component labeling using union-find.
    Returns: (label_image, num_labels, component_info, raw_labels)
    component_info[label] = {'size', 'bbox': (x, y, w, h), 'centroid': (cx, cy)}
    label 0 = background.
    """
    assert img.mode == 'L'
    W, H = img.width, img.height
    src = img.planes[0]

    parent = list(range(W * H + 2))

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    labels = [0] * (W * H)
    next_label = 1

    nb_offsets = [(-1, 0), (0, -1)] if connectivity == 4 else [(-1, -1), (-1, 0), (-1, 1), (0, -1)]

    for r in range(H):
        for c in range(W):
            i = r * W + c
            if src[i] < 0.5:
                continue
            nb_labels = []
            for dr, dc in nb_offsets:
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W:
                    nb = labels[nr * W + nc]
                    if nb > 0:
                        nb_labels.append(nb)
            if not nb_labels:
                labels[i] = next_label
                next_label += 1
            else:
                mn = min(nb_labels)
                labels[i] = mn
                for lb in nb_labels:
                    union(lb, mn)

    # Second pass: resolve
    remap = {}
    new_label = 0
    for r in range(H):
        for c in range(W):
            i = r * W + c
            if labels[i]:
                root = find(labels[i])
                if root not in remap:
                    new_label += 1
                    remap[root] = new_label
                labels[i] = remap[root]

    num_labels = new_label

    # Compute stats
    info = {lb: {'size': 0, 'min_r': H, 'max_r': 0, 'min_c': W, 'max_c': 0,
                 'sum_r': 0, 'sum_c': 0} for lb in range(1, num_labels + 1)}
    for r in range(H):
        for c in range(W):
            lb = labels[r * W + c]
            if lb:
                d = info[lb]
                d['size'] += 1
                d['sum_r'] += r; d['sum_c'] += c
                if r < d['min_r']: d['min_r'] = r
                if r > d['max_r']: d['max_r'] = r
                if c < d['min_c']: d['min_c'] = c
                if c > d['max_c']: d['max_c'] = c

    comp_info = {}
    for lb, d in info.items():
        s = d['size']
        comp_info[lb] = {
            'size': s,
            'bbox': (d['min_c'], d['min_r'], d['max_c'] - d['min_c'] + 1, d['max_r'] - d['min_r'] + 1),
            'centroid': (d['sum_c'] / s, d['sum_r'] / s),
        }

    # Build colorized label image
    label_img = colorize_labels(labels, num_labels, W, H)
    return label_img, num_labels, comp_info, labels


def colorize_labels(labels: list, num_labels: int, W: int, H: int) -> Image:
    """Map integer labels to distinct RGB colors."""
    out = Image(W, H, 'RGB')
    if num_labels == 0:
        return out
    palette = {}
    for lb in range(1, num_labels + 1):
        hue = (lb - 1) / max(1, num_labels)
        r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.90)
        palette[lb] = (r, g, b)
    for i in range(W * H):
        lb = labels[i]
        if lb:
            r, g, b = palette[lb]
            out.planes[0][i] = r
            out.planes[1][i] = g
            out.planes[2][i] = b
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Thresholding (bonus, used in demo & tests)
# ═══════════════════════════════════════════════════════════════════════════════

def threshold_otsu(img: Image) -> tuple:
    """Otsu's method. Returns (threshold_value, binary_image)."""
    if img.mode != 'L':
        img = img.grayscale()
    src = img.planes[0]
    n = img.width * img.height
    hist = [0] * 256
    for v in src:
        hist[min(255, max(0, int(v * 255)))] += 1

    total = n
    sum_all = sum(i * hist[i] for i in range(256))
    sum_bg = w_bg = 0
    best_t = 0; best_var = 0.0

    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        mb = sum_bg / w_bg
        mf = (sum_all - sum_bg) / w_fg
        var = w_bg * w_fg * (mb - mf) ** 2
        if var > best_var:
            best_var = var; best_t = t

    # Use bin midpoint so that pixels exactly in the threshold bin fall on the
    # background side — avoids treating 0.0-valued pixels as foreground when best_t=0.
    t_float = (best_t + 0.5) / 255.0
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [1.0 if v >= t_float else 0.0 for v in src]
    return t_float, out


def threshold_adaptive(img: Image, block_size: int = 15, C: float = 0.02) -> Image:
    """Adaptive local mean thresholding."""
    if img.mode != 'L':
        img = img.grayscale()
    k = [1.0 / block_size] * block_size
    local_mean = _convolve1d_v(_convolve1d_h(img, k), k)
    src, lm = img.planes[0], local_mean.planes[0]
    out = Image(img.width, img.height, 'L')
    out.planes[0] = [1.0 if src[i] > lm[i] - C else 0.0 for i in range(img.width * img.height)]
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Hough Line Transform (S1)
# ═══════════════════════════════════════════════════════════════════════════════

def hough_lines(img: Image, theta_steps: int = 180, rho_res: float = 1.0,
                threshold: float = 0.4, top_n: int = 20, nms_range: int = 8) -> list:
    """
    Standard Hough transform on a binary edge image ('L' mode, edges=1.0).
    Returns list of (rho, theta_degrees, normalized_score) sorted by score.
    theta_steps: number of theta bins in [0°, 180°).
    """
    assert img.mode == 'L'
    W, H = img.width, img.height
    src = img.planes[0]

    diag = math.hypot(W, H)
    n_rho = int(2 * diag / rho_res) + 2
    rho_off = diag

    thetas = [t * math.pi / theta_steps for t in range(theta_steps)]
    cos_t = [math.cos(t) for t in thetas]
    sin_t = [math.sin(t) for t in thetas]

    acc = [0] * (n_rho * theta_steps)

    for r in range(H):
        for c in range(W):
            if src[r * W + c] < 0.5:
                continue
            for ti in range(theta_steps):
                rho = c * cos_t[ti] + r * sin_t[ti]
                ri = int((rho + rho_off) / rho_res)
                if 0 <= ri < n_rho:
                    acc[ri * theta_steps + ti] += 1

    max_val = max(acc) if acc else 0
    if max_val == 0:
        return []

    thresh = threshold * max_val
    used = bytearray(len(acc))
    peaks = []

    for idx in sorted(range(len(acc)), key=lambda i: -acc[i]):
        if acc[idx] < thresh or len(peaks) >= top_n:
            break
        if used[idx]:
            continue
        ri = idx // theta_steps
        ti = idx % theta_steps
        rho_val = ri * rho_res - rho_off
        peaks.append((rho_val, ti * 180.0 / theta_steps, acc[idx] / max_val))
        for dr in range(-nms_range, nms_range + 1):
            for dt in range(-nms_range, nms_range + 1):
                nr2 = ri + dr; nt2 = (ti + dt) % theta_steps
                if 0 <= nr2 < n_rho:
                    used[nr2 * theta_steps + nt2] = 1

    return peaks


def draw_lines(img: Image, lines: list, color=(1.0, 0.2, 0.2)) -> Image:
    """Draw Hough lines (rho, theta_deg, score) on an RGB copy."""
    out = img.to_rgb()
    W, H = out.width, out.height
    for rho, theta_deg, _ in lines:
        theta = math.radians(theta_deg)
        ct, st = math.cos(theta), math.sin(theta)
        pts = []
        if abs(ct) > 1e-6:
            for y in (0, H - 1):
                x = (rho - y * st) / ct
                if 0 <= x < W:
                    pts.append((int(x + 0.5), y))
        if abs(st) > 1e-6:
            for x in (0, W - 1):
                y = (rho - x * ct) / st
                if 0 <= y < H:
                    pts.append((x, int(y + 0.5)))
        if len(pts) >= 2:
            _draw_line(out, pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], color)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Template Matching (S2)
# ═══════════════════════════════════════════════════════════════════════════════

def template_match_ncc(img: Image, tmpl: Image) -> Image:
    """
    Normalized Cross-Correlation template matching.
    Returns response map (L mode, 0–1; 1 = perfect match).
    Uses summed-area tables for O(1) patch sum/sum² per position.
    Raises ValueError if template is larger than the image.
    """
    if img.mode != 'L':
        img = img.grayscale()
    if tmpl.mode != 'L':
        tmpl = tmpl.grayscale()

    W, H = img.width, img.height
    TW, TH = tmpl.width, tmpl.height
    if TW > W or TH > H:
        raise ValueError(
            f"Template ({TW}×{TH}) is larger than image ({W}×{H}) — no valid positions"
        )
    n_t = TW * TH

    src = img.planes[0]
    tpl = tmpl.planes[0]

    # Template statistics
    t_mean = sum(tpl) / n_t
    t_std = math.sqrt(max(0.0, sum((v - t_mean) ** 2 for v in tpl) / n_t))

    # Summed-area tables for src and src²
    ii  = [0.0] * (W * H)   # integral image
    ii2 = [0.0] * (W * H)   # integral image of squares
    for r in range(H):
        rs = 0.0; rs2 = 0.0
        for c in range(W):
            i = r * W + c
            rs += src[i]; rs2 += src[i] * src[i]
            above  = ii [(r - 1) * W + c] if r > 0 else 0.0
            above2 = ii2[(r - 1) * W + c] if r > 0 else 0.0
            ii [i] = rs  + above
            ii2[i] = rs2 + above2

    def box_sum(ii_, r0, c0, r1, c1):
        s = ii_[r1 * W + c1]
        if r0 > 0: s -= ii_[(r0 - 1) * W + c1]
        if c0 > 0: s -= ii_[r1 * W + c0 - 1]
        if r0 > 0 and c0 > 0: s += ii_[(r0 - 1) * W + c0 - 1]
        return s

    out = Image(W, H, 'L')
    op = out.planes[0]

    if t_std < 1e-9:
        return out  # flat template — no meaningful match

    for r in range(H - TH + 1):
        for c in range(W - TW + 1):
            r0, c0, r1, c1 = r, c, r + TH - 1, c + TW - 1
            p_sum  = box_sum(ii,  r0, c0, r1, c1)
            p_sum2 = box_sum(ii2, r0, c0, r1, c1)
            p_mean = p_sum / n_t
            p_var  = p_sum2 / n_t - p_mean * p_mean
            p_std  = math.sqrt(max(0.0, p_var))
            if p_std < 1e-9:
                continue

            # Cross-correlation: Σ (patch - p_mean)(tmpl - t_mean) / (n * std_p * std_t)
            cross = 0.0
            for tr in range(TH):
                for tc in range(TW):
                    cross += src[(r + tr) * W + (c + tc)] * tpl[tr * TW + tc]
            ncc = (cross / n_t - p_mean * t_mean) / (p_std * t_std)
            ncc = max(-1.0, min(1.0, ncc))
            op[(r + TH // 2) * W + (c + TW // 2)] = (ncc + 1.0) / 2.0

    return out


def find_matches(corr: Image, tmpl_w: int, tmpl_h: int,
                 threshold: float = 0.85, top_n: int = 10) -> list:
    """Extract top match locations from correlation map. Returns [(x, y, score)]."""
    W, H = corr.width, corr.height
    cp = corr.planes[0]
    candidates = sorted(
        [(c - tmpl_w // 2, r - tmpl_h // 2, cp[r * W + c])
         for r in range(tmpl_h // 2, H - tmpl_h // 2)
         for c in range(tmpl_w // 2, W - tmpl_w // 2)
         if cp[r * W + c] >= threshold],
        key=lambda x: -x[2]
    )
    result = []
    for x, y, s in candidates:
        if all(abs(x - rx) >= tmpl_w or abs(y - ry) >= tmpl_h for rx, ry, _ in result):
            result.append((x, y, s))
        if len(result) >= top_n:
            break
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Drawing utilities
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_line(img: Image, x0: int, y0: int, x1: int, y1: int, color: tuple):
    """Bresenham line draw in-place."""
    W, H = img.width, img.height
    n_ch = img.n_channels
    dx = abs(x1 - x0); dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if 0 <= y0 < H and 0 <= x0 < W:
            idx = y0 * W + x0
            for ch in range(min(n_ch, len(color))):
                img.planes[ch][idx] = color[ch]
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x0 += sx
        if e2 < dx:
            err += dx; y0 += sy


def draw_corners(img: Image, corners: list, color=(1.0, 0.1, 0.1), radius: int = 3) -> Image:
    """Draw hollow circles at corner locations on an RGB copy."""
    out = img.to_rgb()
    W, H = out.width, out.height
    for r, c, _ in corners:
        for angle_deg in range(0, 360, 5):
            a = math.radians(angle_deg)
            pr = int(r + radius * math.sin(a))
            pc = int(c + radius * math.cos(a))
            if 0 <= pr < H and 0 <= pc < W:
                i = pr * W + pc
                for ch, v in enumerate(color):
                    out.planes[ch][i] = v
    return out


def draw_rect(img: Image, x: int, y: int, w: int, h: int, color=(0.0, 1.0, 0.0)) -> Image:
    out = img if img.mode == 'RGB' else img.to_rgb()
    _draw_line(out, x, y, x + w - 1, y, color)
    _draw_line(out, x + w - 1, y, x + w - 1, y + h - 1, color)
    _draw_line(out, x + w - 1, y + h - 1, x, y + h - 1, color)
    _draw_line(out, x, y + h - 1, x, y, color)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Synthetic image generation (for demo / tests)
# ═══════════════════════════════════════════════════════════════════════════════

def make_checkerboard(w: int, h: int, cell: int = 16) -> Image:
    img = Image(w, h, 'L')
    for r in range(h):
        for c in range(w):
            img.planes[0][r * w + c] = 1.0 if ((r // cell) + (c // cell)) % 2 == 0 else 0.0
    return img


def make_shapes(w: int, h: int) -> Image:
    """Grayscale image with a rectangle, filled circle, and filled triangle."""
    img = Image(w, h, 'L', fill=0.0)
    p = img.planes[0]
    # Rectangle
    for r in range(h // 8, h // 3):
        for c in range(w // 8, w // 2 - w // 8):
            p[r * w + c] = 1.0
    # Circle
    cx, cy, cr = int(w * 0.70), int(h * 0.35), min(w, h) // 6
    for r in range(h):
        for c in range(w):
            if (c - cx) ** 2 + (r - cy) ** 2 <= cr * cr:
                p[r * w + c] = 1.0
    # Triangle (filled, lower half)
    apex_r = int(h * 0.55); base_r = int(h * 0.88); mid_c = w // 2
    half_base = int(w * 0.22)
    for r in range(apex_r, base_r + 1):
        frac = (r - apex_r) / max(1, base_r - apex_r)
        hw = int(frac * half_base)
        for c in range(mid_c - hw, mid_c + hw + 1):
            if 0 <= c < w:
                p[r * w + c] = 1.0
    return img


def make_circles(w: int, h: int, n: int = 4, radius: int = 14) -> Image:
    """RGB image with n non-overlapping colored circles — used for template matching."""
    import random
    rng = random.Random(7)
    img = Image(w, h, 'RGB', fill=0.05)
    centers = []
    attempts = 0
    while len(centers) < n and attempts < 2000:
        cx = rng.randint(radius + 4, w - radius - 4)
        cy = rng.randint(radius + 4, h - radius - 4)
        if all(math.hypot(cx - px, cy - py) > 2 * radius + 8 for px, py in centers):
            centers.append((cx, cy))
            rv = rng.uniform(0.5, 1.0)
            gv = rng.uniform(0.1, 0.5)
            bv = rng.uniform(0.1, 0.5)
            for r in range(h):
                for c in range(w):
                    if (c - cx) ** 2 + (r - cy) ** 2 <= radius * radius:
                        img.planes[0][r * w + c] = rv
                        img.planes[1][r * w + c] = gv
                        img.planes[2][r * w + c] = bv
        attempts += 1
    return img, centers


def make_lines_image(w: int, h: int) -> Image:
    """White lines on black — for Hough demo."""
    img = Image(w, h, 'L', fill=0.0)
    p = img.planes[0]
    # Horizontal
    r0 = h // 3
    for c in range(w): p[r0 * w + c] = 1.0
    # Vertical
    c0 = w // 3
    for r in range(h): p[r * w + c0] = 1.0
    # Diagonal
    for t in range(min(w, h)):
        r = h - 1 - t; c = t
        if 0 <= r < h and 0 <= c < w: p[r * w + c] = 1.0
    return img


# ═══════════════════════════════════════════════════════════════════════════════
# HTML pipeline visualizer (S3)
# ═══════════════════════════════════════════════════════════════════════════════

def _img_to_b64(img: Image) -> str:
    src = img if img.mode == 'RGB' else img.to_rgb()
    return base64.b64encode(encode_png(src)).decode()


def build_pipeline_html(stages: list) -> str:
    """
    stages: list of (label, Image) pairs.
    Returns a self-contained HTML pipeline viewer.
    """
    stage_json = []
    for label, img in stages:
        b64 = _img_to_b64(img)
        stage_json.append(json.dumps({
            'name': label,
            'src': f'data:image/png;base64,{b64}',
            'w': img.width,
            'h': img.height,
        }))
    stages_js = '[' + ','.join(stage_json) + ']'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Optic — CV Pipeline</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0d14;color:#d4d4dc;font-family:"SF Mono","Fira Code",monospace;min-height:100vh}}
header{{padding:20px 28px;border-bottom:1px solid #1e1e2e;display:flex;align-items:center;gap:14px}}
.logo{{font-size:22px;font-weight:700;letter-spacing:3px;color:#82aaff}}
.sub{{color:#565f89;font-size:12px}}
.pipe{{display:flex;align-items:flex-start;padding:28px;overflow-x:auto;gap:0}}
.card{{min-width:200px;max-width:240px;background:#13131e;border:1px solid #1e1e2e;border-radius:10px;overflow:hidden;cursor:pointer;transition:.15s border-color,.15s transform}}
.card:hover{{border-color:#82aaff;transform:translateY(-2px)}}
.card-hdr{{padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#82aaff;border-bottom:1px solid #1e1e2e}}
.card img{{display:block;width:100%;image-rendering:pixelated}}
.card-ft{{padding:6px 12px;font-size:10px;color:#3b4261}}
.arrow{{color:#2a2a4a;font-size:18px;padding:0 6px;margin-top:52px;flex-shrink:0}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:99;align-items:center;justify-content:center;flex-direction:column;gap:14px}}
.modal.open{{display:flex}}
.modal img{{max-width:92vw;max-height:82vh;image-rendering:pixelated;border-radius:8px;border:1px solid #1e1e2e}}
.modal-title{{color:#82aaff;font-size:15px;text-align:center}}
.close{{position:absolute;top:18px;right:18px;background:#1e1e2e;border:none;color:#cdd6f4;font-size:18px;width:36px;height:36px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center}}
.info-bar{{background:#0a0a12;border-top:1px solid #1e1e2e;padding:18px 28px;display:flex;flex-wrap:wrap;gap:24px;font-size:11px;color:#565f89}}
.info-item span{{color:#a6b0d0}}
footer{{text-align:center;padding:12px;color:#2a2a3a;font-size:10px;border-top:1px solid #1e1e2e}}
</style>
</head>
<body>
<header>
  <div class="logo">OPTIC</div>
  <div class="sub">Computer Vision Pipeline Visualizer · click any stage to zoom</div>
</header>
<div class="pipe" id="pipe"></div>
<div class="info-bar" id="info-bar">
  <div class="info-item">Stages: <span id="n-stages">0</span></div>
  <div class="info-item">Image size: <span id="img-size">—</span></div>
  <div class="info-item">Zoom: click any card · Esc to close</div>
</div>
<div class="modal" id="modal">
  <button class="close" onclick="closeModal()">✕</button>
  <div class="modal-title" id="modal-title"></div>
  <img id="modal-img" src="" alt="">
</div>
<footer>Optic · Pure Python 3 · No dependencies</footer>
<script>
const STAGES={stages_js};
const pipe=document.getElementById('pipe');
STAGES.forEach((s,i)=>{{
  if(i>0){{const a=document.createElement('div');a.className='arrow';a.textContent='→';pipe.appendChild(a);}}
  const c=document.createElement('div');c.className='card';
  c.innerHTML=`<div class="card-hdr">${{s.name}}</div>
    <img src="${{s.src}}" alt="${{s.name}}">
    <div class="card-ft">${{s.w}}×${{s.h}}</div>`;
  c.onclick=()=>openModal(s);
  pipe.appendChild(c);
}});
document.getElementById('n-stages').textContent=STAGES.length;
if(STAGES.length>0)document.getElementById('img-size').textContent=STAGES[0].w+'×'+STAGES[0].h;
function openModal(s){{
  document.getElementById('modal-title').textContent=s.name;
  document.getElementById('modal-img').src=s.src;
  document.getElementById('modal').classList.add('open');
}}
function closeModal(){{document.getElementById('modal').classList.remove('open');}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});
document.getElementById('modal').addEventListener('click',e=>{{if(e.target===e.currentTarget)closeModal();}});
</script>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════════════════════
# CLI commands
# ═══════════════════════════════════════════════════════════════════════════════

def _load(path: str) -> Image:
    """Load a PNG, with a clear error if the file is missing or not a PNG."""
    if not os.path.exists(path):
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return read_png(path)
    except (ValueError, struct.error) as e:
        print(f"error: cannot read '{path}': {e}", file=sys.stderr)
        sys.exit(1)


def cmd_info(args):
    img = _load(args.image)
    print(f"File:    {args.image}")
    print(f"Mode:    {img.mode}")
    print(f"Size:    {img.width}×{img.height}")
    print(f"Channels:{img.n_channels}")
    for ch_name, ch in zip('RGBA'[:img.n_channels], img.planes):
        mn, mx = min(ch), max(ch)
        mean = sum(ch) / len(ch)
        print(f"  [{ch_name}] min={mn:.4f}  max={mx:.4f}  mean={mean:.4f}")


def cmd_edges(args):
    if args.sigma <= 0:
        print("error: --sigma must be positive", file=sys.stderr); sys.exit(1)
    if not (0 < args.low < args.high < 1):
        print("error: must have 0 < --low < --high < 1", file=sys.stderr); sys.exit(1)
    img = _load(args.image).grayscale()
    result = canny(img, sigma=args.sigma, low=args.low, high=args.high)
    out_path = args.output or _add_suffix(args.image, '_edges')
    write_png(result, out_path)
    n_edges = sum(1 for v in result.planes[0] if v > 0.5)
    print(f"Canny edges → {out_path}  ({n_edges} edge pixels, σ={args.sigma}, low={args.low}, high={args.high})")


def cmd_corners(args):
    img = _load(args.image)
    if args.method == 'harris':
        corners = harris_corners(img, k=args.k, threshold=args.threshold, top_n=args.top)
        print(f"Harris corners: {len(corners)} found (k={args.k})")
    else:
        corners = fast_corners(img, threshold=args.threshold, top_n=args.top)
        print(f"FAST corners: {len(corners)} found")
    out_img = draw_corners(img, corners)
    out_path = args.output or _add_suffix(args.image, f'_{args.method}')
    write_png(out_img, out_path)
    print(f"→ {out_path}")
    for r, c, s in corners[:5]:
        print(f"  ({r:4d}, {c:4d})  score={s:.4f}")


def cmd_morph(args):
    img = _load(args.image)
    if img.mode != 'L':
        img = img.grayscale()
    # Threshold to binary
    _, img = threshold_otsu(img)
    se = make_se(args.se, args.size)
    ops = {
        'dilate': dilate, 'erode': erode,
        'open': opening, 'close': closing,
        'gradient': morph_gradient, 'tophat': top_hat, 'blackhat': black_hat,
    }
    if args.op not in ops:
        print(f"Unknown op '{args.op}'. Choose: {', '.join(ops)}", file=sys.stderr)
        sys.exit(1)
    result = ops[args.op](img, se)
    out_path = args.output or _add_suffix(args.image, f'_{args.op}')
    write_png(result, out_path)
    print(f"Morphology [{args.op}, SE={args.se} size={args.size}] → {out_path}")


def cmd_components(args):
    img = _load(args.image)
    if img.mode != 'L':
        img = img.grayscale()
    _, img = threshold_otsu(img)
    label_img, n_comp, info, _ = connected_components(img, connectivity=args.connectivity)
    out_path = args.output or _add_suffix(args.image, '_labels')
    write_png(label_img, out_path)
    print(f"Connected components: {n_comp} found (connectivity={args.connectivity})")
    for lb in sorted(info)[:10]:
        d = info[lb]
        print(f"  #{lb}: size={d['size']}  bbox={d['bbox']}  centroid=({d['centroid'][0]:.1f},{d['centroid'][1]:.1f})")
    print(f"→ {out_path}")


def cmd_hough(args):
    img = _load(args.image)
    if img.mode != 'L':
        edges = canny(img.grayscale(), sigma=1.4)
    else:
        edges = img
    lines = hough_lines(edges, threshold=args.threshold, top_n=args.top)
    out_img = draw_lines(img, lines)
    out_path = args.output or _add_suffix(args.image, '_hough')
    write_png(out_img, out_path)
    print(f"Hough: {len(lines)} lines detected → {out_path}")
    for rho, theta, score in lines[:8]:
        print(f"  ρ={rho:7.1f}  θ={theta:6.1f}°  score={score:.3f}")


def cmd_match(args):
    img = _load(args.image)
    tmpl = _load(args.template)
    corr = template_match_ncc(img, tmpl)
    matches = find_matches(corr, tmpl.width, tmpl.height, threshold=args.threshold)
    out_img = img.to_rgb()
    for x, y, s in matches:
        draw_rect(out_img, x, y, tmpl.width, tmpl.height, color=(0.0, 1.0, 0.2))
    out_path = args.output or _add_suffix(args.image, '_match')
    write_png(out_img, out_path)
    print(f"Template match: {len(matches)} match(es) found → {out_path}")
    for x, y, s in matches:
        print(f"  ({x}, {y})  NCC={s:.4f}")


def cmd_denoise(args):
    img = _load(args.image)
    result = bilateral_filter(img, sigma_s=args.sigma_s, sigma_r=args.sigma_r)
    out_path = args.output or _add_suffix(args.image, '_denoised')
    write_png(result, out_path)
    print(f"Bilateral filter (σ_s={args.sigma_s}, σ_r={args.sigma_r}) → {out_path}")


def cmd_thresh(args):
    img = _load(args.image).grayscale()
    if args.method == 'otsu':
        t, result = threshold_otsu(img)
        print(f"Otsu threshold: {t:.4f}")
    else:
        result = threshold_adaptive(img, block_size=args.block, C=args.C)
        print(f"Adaptive threshold (block={args.block}, C={args.C})")
    out_path = args.output or _add_suffix(args.image, '_thresh')
    write_png(result, out_path)
    print(f"→ {out_path}")


def cmd_viz(args):
    img = _load(args.image)
    gray = img.grayscale()
    blurred = gaussian_blur(gray, sigma=1.4)
    _, _, mag, _ = sobel(blurred)
    edges = canny(gray)
    corners_list = harris_corners(gray, top_n=60)
    corners_img = draw_corners(img, corners_list)
    lines = hough_lines(edges, top_n=8)
    lines_img = draw_lines(img, lines)
    _, thresh_img = threshold_otsu(gray)
    lbl_img, _, _, _ = connected_components(thresh_img)

    stages = [
        ('Original', img),
        ('Grayscale', gray),
        ('Gaussian Blur σ=1.4', blurred),
        ('Sobel Magnitude', mag.normalize()),
        ('Canny Edges', edges),
        ('Harris Corners', corners_img),
        ('Hough Lines', lines_img),
        ('Otsu Threshold', thresh_img),
        ('Components', lbl_img),
    ]
    html = build_pipeline_html(stages)
    out_path = args.output or (os.path.splitext(args.image)[0] + '_pipeline.html')
    with open(out_path, 'w') as f:
        f.write(html)
    print(f"Pipeline visualizer → {out_path}")
    print(f"Open in browser: file://{os.path.abspath(out_path)}")


def cmd_demo(args):
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    print("═" * 60)
    print("Optic Demo — Computer Vision from Scratch")
    print("═" * 60)

    # 1. Checkerboard → Harris corners
    print("\n[1] Checkerboard + Harris corners")
    checker = make_checkerboard(128, 128, cell=16)
    write_png(checker, f'{out_dir}/checkerboard.png')
    corners_h = harris_corners(checker, top_n=40)
    corner_img = draw_corners(checker, corners_h)
    write_png(corner_img, f'{out_dir}/checkerboard_harris.png')
    print(f"    Harris found {len(corners_h)} corners on {128}×{128} checkerboard")

    # 2. Shapes image → Canny edges + FAST corners
    print("\n[2] Geometric shapes + Canny edges + FAST corners")
    shapes = make_shapes(128, 128)
    write_png(shapes, f'{out_dir}/shapes.png')
    edges_img = canny(shapes, sigma=1.0, low=0.05, high=0.15)
    write_png(edges_img, f'{out_dir}/shapes_canny.png')
    n_edges = sum(1 for v in edges_img.planes[0] if v > 0.5)
    corners_f = fast_corners(shapes, threshold=0.04, top_n=30)
    fast_img = draw_corners(shapes, corners_f, color=(0.0, 1.0, 0.0))
    write_png(fast_img, f'{out_dir}/shapes_fast.png')
    print(f"    Canny: {n_edges} edge pixels")
    print(f"    FAST: {len(corners_f)} corners detected")

    # 3. Morphology + connected components
    print("\n[3] Morphology + connected components")
    se = make_se('disk', 5)
    dilated = dilate(shapes, se)
    eroded  = erode(shapes, se)
    opened  = opening(shapes, se)
    write_png(dilated, f'{out_dir}/shapes_dilate.png')
    write_png(eroded,  f'{out_dir}/shapes_erode.png')
    write_png(opened,  f'{out_dir}/shapes_open.png')
    label_img, n_comp, comp_info, _ = connected_components(shapes)
    write_png(label_img, f'{out_dir}/shapes_labels.png')
    print(f"    Dilation/Erosion/Opening written")
    print(f"    Connected components: {n_comp} found")
    for lb in sorted(comp_info)[:3]:
        d = comp_info[lb]
        print(f"      #{lb}: size={d['size']} bbox={d['bbox']}")

    # 4. Hough line transform
    print("\n[4] Hough line transform")
    lines_img_src = make_lines_image(128, 128)
    write_png(lines_img_src, f'{out_dir}/lines_src.png')
    # Add slight noise
    import random; rng = random.Random(13)
    noisy = lines_img_src.copy()
    for i in range(128 * 128):
        noisy.planes[0][i] = min(1.0, max(0.0, noisy.planes[0][i] + rng.gauss(0, 0.08)))
    # Canny on noisy version
    edges_hough = canny(noisy.grayscale() if noisy.mode != 'L' else noisy, sigma=0.8, low=0.05, high=0.15)
    lines_found = hough_lines(edges_hough, threshold=0.3, top_n=6)
    lines_drawn = draw_lines(lines_img_src, lines_found, color=(1.0, 0.3, 0.0))
    write_png(lines_drawn, f'{out_dir}/lines_hough.png')
    print(f"    Hough detected {len(lines_found)} lines")
    for rho, theta, score in lines_found:
        print(f"      ρ={rho:7.1f}  θ={theta:5.1f}°  score={score:.3f}")

    # 5. Template matching
    print("\n[5] Template matching (NCC)")
    circles_img, centers = make_circles(128, 128, n=4, radius=12)
    write_png(circles_img, f'{out_dir}/circles.png')
    # Extract a 26×26 template around the first circle center
    if centers:
        cx, cy = centers[0]
        tw, th = 26, 26
        tmpl = circles_img.grayscale().crop(cx - tw // 2, cy - th // 2, tw, th)
        write_png(tmpl, f'{out_dir}/template.png')
        corr = template_match_ncc(circles_img.grayscale(), tmpl)
        matches = find_matches(corr, tw, th, threshold=0.70)
        match_drawn = circles_img.to_rgb()
        for x, y, s in matches:
            draw_rect(match_drawn, x, y, tw, th)
        write_png(match_drawn, f'{out_dir}/circles_match.png')
        print(f"    Template: {tw}×{th}  Matches found: {len(matches)}")
        for x, y, s in matches:
            print(f"      ({x:3d},{y:3d}) NCC={s:.4f}")

    # 6. Bilateral denoising (stretch S4)
    print("\n[6] Bilateral filter denoising (stretch S4)")
    import random; rng2 = random.Random(99)
    noisy_shapes = shapes.copy()
    for i in range(128 * 128):
        noisy_shapes.planes[0][i] = min(1.0, max(0.0,
            noisy_shapes.planes[0][i] + rng2.gauss(0, 0.12)))
    gauss_denoised   = gaussian_blur(noisy_shapes, sigma=1.5)
    bilat_denoised   = bilateral_filter(noisy_shapes, sigma_s=2.0, sigma_r=0.15)
    write_png(noisy_shapes,   f'{out_dir}/shapes_noisy.png')
    write_png(gauss_denoised, f'{out_dir}/shapes_gauss_denoise.png')
    write_png(bilat_denoised, f'{out_dir}/shapes_bilateral.png')
    # Compute edge-preservation: run Canny on both, compare edge counts at true boundaries
    edges_gauss = canny(gauss_denoised, sigma=1.0, low=0.05, high=0.15)
    edges_bilat = canny(bilat_denoised, sigma=1.0, low=0.05, high=0.15)
    n_g = sum(1 for v in edges_gauss.planes[0] if v > 0.5)
    n_b = sum(1 for v in edges_bilat.planes[0] if v > 0.5)
    print(f"    Noisy image: Gaussian denoising → {n_g} edges, Bilateral → {n_b} edges")
    print(f"    (Bilateral preserves sharp edges; Gaussian blurs them out)")

    # 7. Prewitt/Scharr comparison
    print("\n[7] Edge operator comparison (Sobel/Prewitt/Scharr)")
    _, _, sob_mag, _ = sobel(shapes)
    _, _, pre_mag, _ = prewitt(shapes)
    _, _, scha_mag, _ = scharr(shapes)
    write_png(sob_mag.normalize(), f'{out_dir}/shapes_sobel.png')
    write_png(pre_mag.normalize(), f'{out_dir}/shapes_prewitt.png')
    write_png(scha_mag.normalize(), f'{out_dir}/shapes_scharr.png')
    print(f"    Sobel/Prewitt/Scharr magnitude images written")

    # 8. Pipeline visualizer HTML
    print("\n[8] HTML pipeline visualizer")
    blurred_s = gaussian_blur(shapes, 1.4)
    _, _, mag_s, _ = sobel(blurred_s)
    _, thresh_s = threshold_otsu(shapes)
    lbl_s, _, _, _ = connected_components(thresh_s)

    stages = [
        ('Original', shapes),
        ('Noisy (+Gaussian noise)', noisy_shapes),
        ('Gaussian Denoise', gauss_denoised),
        ('Bilateral Denoise', bilat_denoised),
        ('Gaussian Blur', blurred_s),
        ('Sobel Magnitude', mag_s.normalize()),
        ('Canny Edges', edges_img),
        ('Harris Corners', corner_img.grayscale()),
        ('FAST Corners', fast_img),
        ('Dilation', dilated),
        ('Erosion', eroded),
        ('Components', lbl_s),
        ('Hough Lines', lines_drawn),
    ]
    html = build_pipeline_html(stages)
    html_path = f'{out_dir}/pipeline.html'
    with open(html_path, 'w') as f:
        f.write(html)
    print(f"    → {html_path}")
    print(f"    Open: file://{os.path.abspath(html_path)}")

    print("\n" + "═" * 60)
    print(f"Demo complete. Output files in: {out_dir}/")
    print("═" * 60)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _add_suffix(path: str, suffix: str) -> str:
    base, ext = os.path.splitext(path)
    return base + suffix + (ext or '.png')


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(prog='optic', description='Optic — Computer Vision from Scratch')
    sub = ap.add_subparsers(dest='cmd', required=True)

    # info
    p = sub.add_parser('info', help='Show image metadata')
    p.add_argument('image')

    # edges
    p = sub.add_parser('edges', help='Canny edge detection')
    p.add_argument('image')
    p.add_argument('--sigma', type=float, default=1.4)
    p.add_argument('--low',   type=float, default=0.10)
    p.add_argument('--high',  type=float, default=0.20)
    p.add_argument('-o', '--output')

    # corners
    p = sub.add_parser('corners', help='Corner detection (harris or fast)')
    p.add_argument('image')
    p.add_argument('--method', choices=['harris', 'fast'], default='harris')
    p.add_argument('--k', type=float, default=0.04, help='Harris k parameter')
    p.add_argument('--threshold', type=float, default=0.01)
    p.add_argument('--top', type=int, default=100)
    p.add_argument('-o', '--output')

    # morph
    p = sub.add_parser('morph', help='Morphological operation')
    p.add_argument('image')
    p.add_argument('op', choices=['dilate', 'erode', 'open', 'close', 'gradient', 'tophat', 'blackhat'])
    p.add_argument('--se',   default='cross', choices=['cross', 'square', 'disk'])
    p.add_argument('--size', type=int, default=5)
    p.add_argument('-o', '--output')

    # components
    p = sub.add_parser('components', help='Connected component labeling')
    p.add_argument('image')
    p.add_argument('--connectivity', type=int, default=8, choices=[4, 8])
    p.add_argument('-o', '--output')

    # hough
    p = sub.add_parser('hough', help='Hough line transform')
    p.add_argument('image')
    p.add_argument('--threshold', type=float, default=0.4)
    p.add_argument('--top', type=int, default=10)
    p.add_argument('-o', '--output')

    # match
    p = sub.add_parser('match', help='Template matching (NCC)')
    p.add_argument('image')
    p.add_argument('template')
    p.add_argument('--threshold', type=float, default=0.80)
    p.add_argument('-o', '--output')

    # thresh
    p = sub.add_parser('thresh', help='Image thresholding')
    p.add_argument('image')
    p.add_argument('--method', choices=['otsu', 'adaptive'], default='otsu')
    p.add_argument('--block', type=int, default=15, help='Adaptive block size')
    p.add_argument('--C', type=float, default=0.02, help='Adaptive constant')
    p.add_argument('-o', '--output')

    # denoise (S4 stretch)
    p = sub.add_parser('denoise', help='Bilateral filter: edge-preserving denoising')
    p.add_argument('image')
    p.add_argument('--sigma-s', type=float, default=2.0, help='Spatial sigma (pixels)')
    p.add_argument('--sigma-r', type=float, default=0.15, help='Range sigma (intensity 0-1)')
    p.add_argument('-o', '--output')

    # viz
    p = sub.add_parser('viz', help='Generate HTML pipeline visualizer for an image')
    p.add_argument('image')
    p.add_argument('-o', '--output')

    # demo
    p = sub.add_parser('demo', help='Run full demo with synthetic images')
    p.add_argument('--out-dir', default='demo_out')

    args = ap.parse_args()
    dispatch = {
        'info': cmd_info, 'edges': cmd_edges, 'corners': cmd_corners,
        'morph': cmd_morph, 'components': cmd_components, 'hough': cmd_hough,
        'match': cmd_match, 'thresh': cmd_thresh, 'denoise': cmd_denoise,
        'viz': cmd_viz, 'demo': cmd_demo,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
