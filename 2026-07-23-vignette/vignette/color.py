"""RGB <-> YCbCr color conversion (ITU-R BT.601 / JFIF full-range, the
color space every baseline JPEG file's pixel data is actually stored in)."""


def rgb_to_ycbcr(r, g, b):
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
    return y, cb, cr


def ycbcr_to_rgb(y, cb, cr):
    r = y + 1.402 * (cr - 128.0)
    g = y - 0.344136 * (cb - 128.0) - 0.714136 * (cr - 128.0)
    b = y + 1.772 * (cb - 128.0)
    return _clamp(r), _clamp(g), _clamp(b)


def _clamp(v):
    v = int(round(v))
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v
