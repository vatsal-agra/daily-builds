"""RGB <-> YCbCr color conversion and chroma subsampling/upsampling.

JPEG (via the JFIF profile) uses the full-range ITU-R BT.601 YCbCr matrix,
not the "studio swing" (16-235) matrix video codecs use. Y, Cb, Cr all
occupy the full 0..255 range. These are the exact IJG (libjpeg) constants.
"""
import math

# Forward RGB -> YCbCr (BT.601, full range)
def rgb_to_ycbcr(r, g, b):
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
    return y, cb, cr


def ycbcr_to_rgb(y, cb, cr):
    r = y + 1.402 * (cr - 128.0)
    g = y - 0.344136 * (cb - 128.0) - 0.714136 * (cr - 128.0)
    b = y + 1.772 * (cb - 128.0)
    return r, g, b


def _clamp255(v):
    if v < 0.0:
        return 0
    if v > 255.0:
        return 255
    return int(v + 0.5)


class Image:
    """A simple planar RGB image: width, height, and flat r/g/b byte lists."""

    def __init__(self, width, height, r, g, b):
        if width < 0 or height < 0:
            raise ValueError(f"image dimensions must be non-negative, got {width}x{height}")
        if not (len(r) == len(g) == len(b) == width * height):
            raise ValueError(
                f"pixel plane length mismatch for a {width}x{height} image: "
                f"expected {width * height}, got r={len(r)} g={len(g)} b={len(b)}"
            )
        self.width = width
        self.height = height
        self.r = r
        self.g = g
        self.b = b

    def to_ycbcr_planes(self):
        """Convert to three full-resolution float planes Y, Cb, Cr."""
        n = self.width * self.height
        y = [0.0] * n
        cb = [0.0] * n
        cr = [0.0] * n
        r, g, b = self.r, self.g, self.b
        for i in range(n):
            yy, ccb, ccr = rgb_to_ycbcr(r[i], g[i], b[i])
            y[i] = yy
            cb[i] = ccb
            cr[i] = ccr
        return y, cb, cr

    @staticmethod
    def from_ycbcr_planes(width, height, y, cb, cr):
        n = width * height
        r = [0] * n
        g = [0] * n
        b = [0] * n
        for i in range(n):
            rr, gg, bb = ycbcr_to_rgb(y[i], cb[i], cr[i])
            r[i] = _clamp255(rr)
            g[i] = _clamp255(gg)
            b[i] = _clamp255(bb)
        return Image(width, height, r, g, b)


def subsample_plane(plane, width, height, hfactor, vfactor):
    """Box-filter downsample a plane by (hfactor, vfactor) (1 or 2).

    JPEG subsampling groups hfactor x vfactor source pixels into one
    chroma sample by averaging -- this is what real JPEG encoders do
    (a simple box filter), not point-sampling (which would alias badly).
    Output dimensions are ceil(width/hfactor) x ceil(height/vfactor).
    """
    out_w = (width + hfactor - 1) // hfactor
    out_h = (height + vfactor - 1) // vfactor
    out = [0.0] * (out_w * out_h)
    for oy in range(out_h):
        for ox in range(out_w):
            total = 0.0
            count = 0
            for dy in range(vfactor):
                sy = oy * vfactor + dy
                if sy >= height:
                    sy = height - 1
                for dx in range(hfactor):
                    sx = ox * hfactor + dx
                    if sx >= width:
                        sx = width - 1
                    total += plane[sy * width + sx]
                    count += 1
            out[oy * out_w + ox] = total / count
    return out, out_w, out_h


def pad_plane(plane, w, h, target_w, target_h):
    """Edge-replicate a plane out to (target_w, target_h), padding on the
    right/bottom. JPEG requires every plane to be a whole number of 8x8
    blocks; replicating the edge (rather than zero-padding) keeps the
    padding region from injecting a sharp, ringing-inducing edge right at
    the image boundary that quantization would then have to spend bits on.
    """
    assert target_w >= w and target_h >= h
    out = [0.0] * (target_w * target_h)
    for y in range(target_h):
        sy = min(y, h - 1)
        srow = sy * w
        drow = y * target_w
        for x in range(target_w):
            sx = min(x, w - 1)
            out[drow + x] = plane[srow + sx]
    return out


def crop_plane(plane, padded_w, target_w, target_h):
    """Inverse of pad_plane: take the top-left target_w x target_h region."""
    out = [0.0] * (target_w * target_h)
    for y in range(target_h):
        srow = y * padded_w
        drow = y * target_w
        out[drow:drow + target_w] = plane[srow:srow + target_w]
    return out


def upsample_plane(plane, sub_w, sub_h, hfactor, vfactor, out_w, out_h):
    """Bilinear upsample a subsampled chroma plane back to out_w x out_h.

    The JPEG standard leaves chroma reconstruction filtering entirely up
    to the decoder -- it only defines what was thrown away, not how to
    interpolate it back. Real decoders (libjpeg's "fancy upsampling",
    browsers) use a smooth filter rather than nearest-neighbor block
    replication, because block replication reintroduces hard edges at
    every subsample-grid boundary that the encoder's box-filter
    subsampling never had. This uses the standard half-pixel-center
    bilinear convention (each output sample's source position is
    `(i + 0.5) / factor - 0.5` in the subsampled grid), with edge
    clamping, which is a genuine continuous interpolation of the encoder's
    box-filtered chroma samples -- not a bit-exact match to any one
    reference decoder's specific filter (no filter choice here is
    mandated by the spec), but visibly smoother and measurably closer to
    a real decoder's chroma reconstruction than nearest-neighbor.
    """
    if hfactor == 1 and vfactor == 1:
        return list(plane)

    def source_coords(factor, n):
        # For each of n output positions, the fractional source position
        # and the two neighboring subsampled-grid indices to blend.
        coords = []
        for i in range(n):
            s = (i + 0.5) / factor - 0.5
            i0 = int(math.floor(s))
            frac = s - i0
            coords.append((i0, frac))
        return coords

    xs = source_coords(hfactor, out_w)
    ys = source_coords(vfactor, out_h)

    out = [0.0] * (out_w * out_h)
    for y in range(out_h):
        sy0, fy = ys[y]
        sy0c = min(max(sy0, 0), sub_h - 1)
        sy1c = min(max(sy0 + 1, 0), sub_h - 1)
        row0 = sy0c * sub_w
        row1 = sy1c * sub_w
        drow = y * out_w
        for x in range(out_w):
            sx0, fx = xs[x]
            sx0c = min(max(sx0, 0), sub_w - 1)
            sx1c = min(max(sx0 + 1, 0), sub_w - 1)
            top = plane[row0 + sx0c] * (1 - fx) + plane[row0 + sx1c] * fx
            bot = plane[row1 + sx0c] * (1 - fx) + plane[row1 + sx1c] * fx
            out[drow + x] = top * (1 - fy) + bot * fy
    return out
