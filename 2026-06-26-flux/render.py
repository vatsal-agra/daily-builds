"""
Flux renderer: colormap functions + from-scratch PNG encoder.
No Pillow, no external imaging libraries — only zlib from stdlib.
"""

import struct
import zlib
import numpy as np
from typing import Tuple


# ---------------------------------------------------------------------------
# PNG encoder (hand-rolled, stdlib zlib only)
# ---------------------------------------------------------------------------

def encode_png(rgb: np.ndarray) -> bytes:
    """
    Encode an (H, W, 3) uint8 numpy array as a valid PNG file.
    Uses filter type 0 (None) for simplicity — zlib handles compression.
    """
    H, W, _ = rgb.shape
    assert rgb.dtype == np.uint8 and rgb.shape[2] == 3

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + ctype + data
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    # IDAT: prepend filter byte 0x00 to each row
    raw_rows = bytearray()
    for row in rgb:
        raw_rows.append(0x00)        # filter None
        raw_rows.extend(row.tobytes())
    compressed = zlib.compress(bytes(raw_rows), 6)
    idat = chunk(b"IDAT", compressed)

    iend = chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


def decode_png(data: bytes) -> np.ndarray:
    """
    Minimal PNG decoder for filter-0 (None) RGB PNG files.
    Returns (H, W, 3) uint8 array. Only handles what encode_png writes.
    """
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    W = H = 0
    raw_idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8]
        cdata = data[pos+8:pos+8+length]
        pos += 12 + length
        if ctype == b"IHDR":
            W, H = struct.unpack(">II", cdata[:8])
        elif ctype == b"IDAT":
            raw_idat.extend(cdata)
        elif ctype == b"IEND":
            break
    decompressed = zlib.decompress(bytes(raw_idat))
    stride = 1 + W * 3
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    for r in range(H):
        assert decompressed[r * stride] == 0, "unsupported PNG filter"
        row = decompressed[r * stride + 1: r * stride + 1 + W * 3]
        rgb[r] = np.frombuffer(row, dtype=np.uint8).reshape(W, 3)
    return rgb


# ---------------------------------------------------------------------------
# Colormaps  (input: 2D float array [0, ∞); output: (H, W, 3) float [0, 1])
# ---------------------------------------------------------------------------

def _normalise(arr: np.ndarray, vmin: float = None, vmax: float = None) -> np.ndarray:
    """Normalise to [0, 1], optionally clamping to [vmin, vmax]."""
    a = arr.copy()
    lo = float(a.min()) if vmin is None else vmin
    hi = float(a.max()) if vmax is None else vmax
    if hi <= lo:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def colormap_fire(t: np.ndarray) -> np.ndarray:
    """Black → dark red → orange → yellow → white fire palette."""
    r = np.clip(3.0 * t, 0.0, 1.0)
    g = np.clip(3.0 * t - 1.0, 0.0, 1.0)
    b = np.clip(3.0 * t - 2.0, 0.0, 1.0)
    return np.stack([r, g, b], axis=-1)


def colormap_plasma(t: np.ndarray) -> np.ndarray:
    """Purple → magenta → orange approximate plasma."""
    r = np.clip(1.66 * t + 0.14, 0.0, 1.0)
    g = np.clip(-0.9 * t * t + 0.56 * t + 0.06, 0.0, 1.0)
    b = np.clip(-1.45 * t + 0.82, 0.0, 1.0)
    return np.stack([r, g, b], axis=-1)


def colormap_cool(t: np.ndarray) -> np.ndarray:
    """Cyan → magenta."""
    r = t
    g = 1.0 - t
    b = np.ones_like(t)
    return np.stack([r, g, b], axis=-1)


def colormap_viridis_approx(t: np.ndarray) -> np.ndarray:
    """Approximate viridis: purple → teal → yellow."""
    r = np.clip(0.28 + 1.19 * t - 0.34 * t * t, 0.0, 1.0)
    g = np.clip(0.00 + 1.22 * t, 0.0, 1.0)
    b = np.clip(0.60 - 0.38 * t, 0.0, 1.0)
    return np.stack([r, g, b], axis=-1)


COLORMAPS = {
    "fire": colormap_fire,
    "plasma": colormap_plasma,
    "cool": colormap_cool,
    "viridis": colormap_viridis_approx,
}


# ---------------------------------------------------------------------------
# Fluid → pixel renderers
# ---------------------------------------------------------------------------

def render_dye(fluid, scale: int = 1) -> np.ndarray:
    """
    Render all dye channels blended additively.
    Returns (H, W, 3) uint8 with H=W=N*scale.
    """
    N = fluid.N
    canvas = np.zeros((N, N, 3), dtype=float)
    for dye in fluid.dyes:
        d = dye.density[1:-1, 1:-1]
        d_norm = np.clip(d, 0.0, 2.0) / 2.0
        for c, col in enumerate(dye.color):
            canvas[:, :, c] += d_norm * col
    canvas = np.clip(canvas, 0.0, 1.0)
    rgb = (canvas * 255).astype(np.uint8)
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    return rgb


def render_speed(fluid, colormap: str = "plasma", scale: int = 1) -> np.ndarray:
    """Render velocity magnitude with a colormap."""
    N = fluid.N
    speed = np.sqrt(fluid.u[1:-1, 1:-1] ** 2 + fluid.v[1:-1, 1:-1] ** 2)
    t = _normalise(speed)
    fn = COLORMAPS.get(colormap, colormap_plasma)
    rgb = fn(t)
    rgb = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    return rgb


def render_vorticity(fluid, colormap: str = "cool", scale: int = 1) -> np.ndarray:
    """Render signed vorticity (curl) with a diverging colormap."""
    N = fluid.N
    omega = fluid.vorticity()[1:-1, 1:-1]
    absmax = float(np.abs(omega).max()) or 1.0
    t = (omega / absmax + 1.0) * 0.5          # remap [-1, 1] → [0, 1]
    fn = COLORMAPS.get(colormap, colormap_cool)
    rgb = fn(t)
    rgb = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    return rgb


def render_composite(fluid, colormap: str = "fire", scale: int = 1) -> np.ndarray:
    """
    Overlay: dye channels in colour + speed halo for visual richness.
    Good default for batch renders.
    """
    N = fluid.N
    dye_layer = np.zeros((N, N, 3), dtype=float)
    total_dye = np.zeros((N, N), dtype=float)
    for dye in fluid.dyes:
        d = np.clip(dye.density[1:-1, 1:-1], 0.0, 2.0)
        total_dye += d
        for c, col in enumerate(dye.color):
            dye_layer[:, :, c] += d * col

    speed = np.sqrt(fluid.u[1:-1, 1:-1] ** 2 + fluid.v[1:-1, 1:-1] ** 2)
    t_speed = _normalise(speed)
    fn = COLORMAPS.get(colormap, colormap_fire)
    speed_rgb = fn(t_speed)

    # Blend: where dye is bright, show dye; elsewhere show speed
    alpha = np.clip(total_dye / 2.0, 0.0, 1.0)[..., np.newaxis]
    composite = alpha * np.clip(dye_layer / (total_dye[..., np.newaxis] + 1e-6), 0, 1) \
              + (1.0 - alpha) * speed_rgb * 0.4
    rgb = np.clip(composite * 255, 0, 255).astype(np.uint8)
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    return rgb


def render_fire(fluid, scale: int = 1) -> np.ndarray:
    """Fire-palette render: maps total dye density through the fire colormap."""
    N = fluid.N
    total = np.zeros((N, N), dtype=float)
    for dye in fluid.dyes:
        total += np.clip(dye.density[1:-1, 1:-1], 0.0, 2.0)
    t = total / (max(1, len(fluid.dyes)) * 2.0)
    rgb_f = colormap_fire(t)
    rgb = np.clip(rgb_f * 255, 0, 255).astype(np.uint8)
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    return rgb


RENDER_MODES = {
    "dye": render_dye,
    "speed": render_speed,
    "vorticity": render_vorticity,
    "composite": render_composite,
    "fire": render_fire,
}


def render_frame(fluid, mode: str = "composite", scale: int = 1) -> np.ndarray:
    fn = RENDER_MODES.get(mode, render_composite)
    rgb = fn(fluid, scale=scale)
    return rgb.transpose(1, 0, 2)  # first axis (x) → columns; second axis (y) → rows
