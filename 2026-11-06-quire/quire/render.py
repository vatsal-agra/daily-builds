"""Page renderer: interprets content streams and paints onto a raster Canvas."""
import math

from .content import Device, Interpreter, hidden_ocgs, mmul, minv, apply, IDENT, Shading, transform_path
from .objects import Stream, Name, Ref
from . import colorspace as cs
from . import raster as R
from . import filters


def page_matrix(box, rot, s):
    x0, y0, x1, y1 = box
    if rot == 90:
        return (0, s, s, 0, -y0 * s, -x0 * s), (y1 - y0) * s, (x1 - x0) * s
    if rot == 180:
        return (-s, 0, 0, s, x1 * s, -y0 * s), (x1 - x0) * s, (y1 - y0) * s
    if rot == 270:
        return (0, -s, -s, 0, y1 * s, x1 * s), (y1 - y0) * s, (x1 - x0) * s
    return (s, 0, 0, -s, -x0 * s, y1 * s), (x1 - x0) * s, (y1 - y0) * s


def _rgb8(rgb):
    return tuple(int(round(c * 255)) for c in rgb)


# ------------------------------------------------------------- images ----
class Img:
    """Decoded image: w,h, rgb bytes (3*w*h), alpha bytes (w*h) or None."""
    def __init__(self, w, h, rgb, alpha=None, stencil=False):
        self.w, self.h, self.rgb, self.alpha, self.stencil = w, h, rgb, alpha, stencil


def _unpack(data, w, h, n, bpc):
    """-> list/bytes of samples, row-major, n comps per pixel, values 0..2^bpc-1"""
    rowbytes = (w * n * bpc + 7) // 8
    need = rowbytes * h
    if len(data) < need:
        data = data + bytes(need - len(data))
    if bpc == 8:
        return data[:need]
    out = bytearray()
    per = w * n
    for y in range(h):
        row = data[y * rowbytes:(y + 1) * rowbytes]
        if bpc == 16:
            out += row[0:2 * per:2]
        elif bpc in (1, 2, 4):
            mask = (1 << bpc) - 1
            vals = []
            for byte in row:
                for sh in range(8 - bpc, -1, -bpc):
                    vals.append((byte >> sh) & mask)
            out += bytes(vals[:per])
    return bytes(out)


def decode_image(doc, stm, fill_rgb, depth=0):
    r = doc.resolve
    d = stm.dict
    w, h = int(r(d.get("Width"))), int(r(d.get("Height")))
    if w <= 0 or h <= 0 or w * h > 80_000_000:
        raise ValueError("bad image size")
    stencil = bool(r(d.get("ImageMask")))
    bpc = 1 if stencil else int(r(d.get("BitsPerComponent")) or 8)
    data, imgf, parm = doc.decode_stream(stm, with_image=True)
    res = getattr(stm, "_inline_res", None)
    dec = r(d.get("Decode"))
    dec = [float(r(v)) for v in dec] if dec else None
    if imgf in ("DCTDecode", "DCT"):
        from .jpeg import decode_jpeg
        jw, jh, jn, samples = decode_jpeg(data)
        w, h, bpc = jw, jh, 8
        data = samples
        if d.get("ColorSpace") is None:
            space = {1: cs.GRAY, 3: cs.RGB, 4: cs.CMYK}[jn]
        else:
            space = cs.parse_colorspace(doc, d.get("ColorSpace"), res)
            if space.n != jn:
                space = {1: cs.GRAY, 3: cs.RGB, 4: cs.CMYK}[jn]
    elif imgf is not None:
        raise ValueError(f"unsupported image filter {imgf}")
    elif stencil:
        space = cs.GRAY
    else:
        space = cs.parse_colorspace(doc, d.get("ColorSpace"), res)
    n = 1 if stencil else space.n
    samples = _unpack(data, w, h, n, bpc) if imgf is None else data
    maxv = (1 << bpc) - 1 if imgf is None else 255
    if stencil:
        inv = bool(dec and dec[0] == 1)
        alpha = bytearray(w * h)
        # 0 = paint (unless Decode [1 0])
        for i, v in enumerate(samples[:w * h]):
            alpha[i] = 255 if ((v == 0) != inv) else 0
        rgb = bytes(_rgb8(fill_rgb)) * (w * h)
        return Img(w, h, rgb, bytes(alpha), True)
    # decode arrays and colour conversion
    if space.kind == "Indexed":
        lut = [bytes(_rgb8(space.to_rgb([i]))) for i in range(space.hival + 1)]
        if dec and dec[0] > dec[1]:
            lut = lut[::-1]
        out = bytearray()
        top = len(lut) - 1
        for v in samples[:w * h]:
            out += lut[v if v <= top else top]
        rgb = bytes(out)
    elif space.kind in ("DeviceGray", "CalGray"):
        tab = bytes((min(255, int(round((v / maxv if maxv else 0) * 255))) for v in range(256)))
        if dec and dec[0] > dec[1]:
            tab = bytes(255 - t for t in tab)
        g = samples[:w * h].translate(tab) if maxv == 255 else bytes(
            min(255, int((v / maxv) * 255 + 0.5)) if not (dec and dec[0] > dec[1]) else min(255, int((1 - v / maxv) * 255 + 0.5))
            for v in samples[:w * h])
        out = bytearray(3 * w * h)
        out[0::3] = g
        out[1::3] = g
        out[2::3] = g
        rgb = bytes(out)
    elif space.kind in ("DeviceRGB", "CalRGB") and not (dec and any(dec[i] > dec[i + 1] for i in (0, 2, 4))):
        rgb = samples[:3 * w * h] if maxv == 255 else bytes(min(255, int(v / maxv * 255 + 0.5)) for v in samples[:3 * w * h])
    else:
        out = bytearray()
        cache = {}
        dlo = [dec[2 * i] if dec else (0.0 if space.kind != "Lab" else [0, space.range[0], space.range[2]][i]) for i in range(n)]
        dhi = [dec[2 * i + 1] if dec else (1.0 if space.kind != "Lab" else [100, space.range[1], space.range[3]][i]) for i in range(n)]
        for i in range(0, w * h * n, n):
            key = samples[i:i + n]
            px = cache.get(key)
            if px is None:
                comps = [dlo[k] + (key[k] / maxv) * (dhi[k] - dlo[k]) for k in range(n)]
                px = bytes(_rgb8(space.to_rgb(comps)))
                if len(cache) < 65536:
                    cache[key] = px
            out += px
        rgb = bytes(out)
    alpha = None
    sm = r(d.get("SMask"))
    mk = r(d.get("Mask"))
    if isinstance(sm, Stream) and depth < 2:
        try:
            s = decode_image(doc, sm, (0, 0, 0), depth + 1)
            alpha = _resample_gray(s.rgb[0::3], s.w, s.h, w, h)
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"SMask skipped: {e}")
    elif isinstance(mk, Stream) and depth < 2:
        try:
            s = decode_image(doc, mk, (0, 0, 0), depth + 1)
            # explicit mask: stencil alpha = paint (sample 0) => *masked out* when stencil painted? Per spec,
            # a mask sample of 1 (after Decode) means masked-out; our stencil alpha is 255 where sample==0 -> opaque.
            alpha = _resample_gray(s.alpha, s.w, s.h, w, h)
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"Mask skipped: {e}")
    elif isinstance(mk, list) and mk and imgf is None:
        ranges = [int(r(v)) for v in mk]
        al = bytearray(b"\xff" * (w * h))
        for i in range(w * h):
            px = samples[i * n:(i + 1) * n]
            if all(ranges[2 * k] <= px[k] <= ranges[2 * k + 1] for k in range(n)):
                al[i] = 0
        alpha = bytes(al)
    if alpha is not None and len(alpha) != w * h:
        alpha = None
    return Img(w, h, rgb, alpha)


def _resample_gray(src, sw, sh, w, h):
    if src is None:
        return None
    if (sw, sh) == (w, h):
        return bytes(src)
    out = bytearray(w * h)
    for y in range(h):
        sy = min(sh - 1, y * sh // h)
        row = src[sy * sw:(sy + 1) * sw]
        for x in range(w):
            out[y * w + x] = row[min(sw - 1, x * sw // w)]
    return bytes(out)


def shrink(img, k):
    """Box-filter downscale by integer factor k."""
    if k <= 1:
        return img
    nw, nh = max(1, img.w // k), max(1, img.h // k)
    rgb = bytearray(3 * nw * nh)
    alpha = bytearray(nw * nh) if img.alpha is not None else None
    for y in range(nh):
        for x in range(nw):
            sr = sg = sb = sa = 0
            cnt = 0
            for yy in range(y * k, min(img.h, y * k + k)):
                base = yy * img.w
                for xx in range(x * k, min(img.w, x * k + k)):
                    i = base + xx
                    a = img.alpha[i] if img.alpha is not None else 255
                    sr += img.rgb[3 * i] * a
                    sg += img.rgb[3 * i + 1] * a
                    sb += img.rgb[3 * i + 2] * a
                    sa += a
                    cnt += 1
            o = y * nw + x
            if sa:
                rgb[3 * o] = sr // sa
                rgb[3 * o + 1] = sg // sa
                rgb[3 * o + 2] = sb // sa
            if alpha is not None:
                alpha[o] = sa // cnt
    return Img(nw, nh, bytes(rgb), bytes(alpha) if alpha is not None else None, img.stencil)


# -------------------------------------------------------------- shading ----
def shading_paint(sh, m):
    """Return callable(x,y)->(r,g,b,a) in device pixels for shading `sh` with shading->device matrix m."""
    full = mmul(tuple(sh.matrix), m) if False else m
    inv = minv(full)
    if inv is None:
        return None
    lut = sh.lut(256) if sh.type in (2, 3) else None
    t0, t1 = sh.domain[0], sh.domain[1]
    bg = sh.background
    ext0, ext1 = sh.extend
    if sh.type == 2:
        x0, y0, x1, y1 = sh.coords[:4]
        dx, dy = x1 - x0, y1 - y0
        den = dx * dx + dy * dy

        def paint(px, py):
            sx = inv[0] * (px + 0.5) + inv[2] * (py + 0.5) + inv[4]
            sy = inv[1] * (px + 0.5) + inv[3] * (py + 0.5) + inv[5]
            t = ((sx - x0) * dx + (sy - y0) * dy) / den if den else 0.0
            if t < 0:
                if not ext0:
                    return (_bg(bg)) if bg else (0, 0, 0, 0.0)
                t = 0.0
            elif t > 1:
                if not ext1:
                    return (_bg(bg)) if bg else (0, 0, 0, 0.0)
                t = 1.0
            c = lut[int(t * 255 + 0.5)]
            return (c[0] * 255, c[1] * 255, c[2] * 255, 1.0)
        return paint
    if sh.type == 3:
        x0, y0, r0, x1, y1, r1 = sh.coords[:6]
        cdx, cdy, dr = x1 - x0, y1 - y0, r1 - r0
        A = cdx * cdx + cdy * cdy - dr * dr

        def paint(px, py):
            sx = inv[0] * (px + 0.5) + inv[2] * (py + 0.5) + inv[4]
            sy = inv[1] * (px + 0.5) + inv[3] * (py + 0.5) + inv[5]
            ex, ey = sx - x0, sy - y0
            B = ex * cdx + ey * cdy + r0 * dr
            C = ex * ex + ey * ey - r0 * r0
            best = None
            if abs(A) < 1e-12:
                if abs(B) > 1e-12:
                    s = C / (2 * B)
                    if r0 + s * dr >= 0:
                        best = s
            else:
                disc = B * B - A * C
                if disc >= 0:
                    sq = math.sqrt(disc)
                    for s in sorted(((B + sq) / A, (B - sq) / A), reverse=True):
                        if r0 + s * dr < 0:
                            continue
                        if 0 <= s <= 1 or (s < 0 and ext0) or (s > 1 and ext1):
                            best = s
                            break
            if best is None:
                return (_bg(bg)) if bg else (0, 0, 0, 0.0)
            s = min(max(best, 0.0), 1.0)
            c = lut[int(s * 255 + 0.5)]
            return (c[0] * 255, c[1] * 255, c[2] * 255, 1.0)
        return paint
    if sh.type == 1:
        dm = sh.matrix
        full2 = mmul(tuple(dm), m)
        inv2 = minv(full2)
        dom = sh.domain if len(sh.domain) == 4 else [0, 1, 0, 1]
        if inv2 is None:
            return None

        def paint(px, py):
            sx = inv2[0] * (px + 0.5) + inv2[2] * (py + 0.5) + inv2[4]
            sy = inv2[1] * (px + 0.5) + inv2[3] * (py + 0.5) + inv2[5]
            if not (dom[0] <= sx <= dom[1] and dom[2] <= sy <= dom[3]):
                return (_bg(bg)) if bg else (0, 0, 0, 0.0)
            comps = sh.fns[0](sx, sy) if len(sh.fns) == 1 else [f(sx, sy)[0] for f in sh.fns]
            c = sh.cs.to_rgb(comps)
            return (c[0] * 255, c[1] * 255, c[2] * 255, 1.0)
        return paint
    return None


def _bg(bg):
    return (bg[0] * 255, bg[1] * 255, bg[2] * 255, 1.0)


# ------------------------------------------------------------- renderer ----
class Renderer(Device):
    def __init__(self, doc, canvas, base):
        self.doc = doc
        self.cv = canvas
        self.base = base
        self.cur_clip = R.Clip(0, 0, canvas.w, canvas.h)
        self.stack = []
        self.scale = math.sqrt(abs(base[0] * base[3] - base[1] * base[2])) or 1.0
        self.glyph_cache = {}
        self.unsupported = set()
        self._tile_cache = {}

    def save(self):
        self.stack.append(self.cur_clip)

    def restore(self):
        if self.stack:
            self.cur_clip = self.stack.pop()

    def _paint_of(self, paint, alpha):
        kind = paint[0]
        if kind == "rgb":
            return _rgb8(paint[1])
        if kind == "shading":
            return shading_paint(paint[1], paint[2])
        if kind == "tiling":
            return self._tiling_paint(paint)
        return (0, 0, 0)

    def fill(self, path, m, evenodd, paint, alpha):
        subs = R.flatten(path, m)
        polys = [p for p, _ in subs if len(p) >= 3]
        if not polys:
            return
        p = self._paint_of(paint, alpha)
        if p is None:
            self.unsupported.add("shading")
            return
        self.cv.fill_polys(polys, evenodd, self.cur_clip, p, alpha)

    def stroke(self, path, m, style, paint, alpha):
        det = abs(m[0] * m[3] - m[1] * m[2])
        sc = math.sqrt(det) if det > 1e-12 else 0.0
        if sc == 0:
            return
        w = style["w"]
        if w * sc < 1.0:
            w = 1.0 / sc
        dash, phase = style["dash"]
        axis = abs(m[1]) < 1e-9 and abs(m[2]) < 1e-9 and abs(abs(m[0]) - abs(m[3])) < 1e-6 * sc
        subs = R.flatten(path, IDENT, tol=0.12 / sc)
        if dash and any(v > 0 for v in dash):
            ns = []
            for pts, closed in subs:
                if len(pts) >= 2:
                    ns += R.dash_polyline(pts, closed, dash, phase)
            subs = ns
        a, b, c, d, e, f = m
        if axis and w * sc < 3.0:
            # stroke adjustment (as poppler does): thin axis-aligned lines are snapped to whole pixels
            wr = max(1, int(round(w * sc)))
            adj = []
            for pts, closed in subs:
                dev = [(a * x + e, d * y + f) for x, y in pts]
                if all(abs(p[0] - q[0]) < 1e-6 or abs(p[1] - q[1]) < 1e-6 for p, q in zip(dev, dev[1:] + ([dev[0]] if closed else []))):
                    if wr % 2:
                        dev = [(math.floor(x) + 0.5, math.floor(y) + 0.5) for x, y in dev]
                    else:
                        dev = [(round(x), round(y)) for x, y in dev]
                adj.append((dev, closed))
            polys = R.stroke_polygons(adj, wr, style["cap"], style["join"], style["miter"])
        else:
            polys_u = R.stroke_polygons(subs, w, style["cap"], style["join"], style["miter"])
            polys = [[(a * x + c * y + e, b * x + d * y + f) for x, y in poly] for poly in polys_u]
        if not polys:
            return
        p = self._paint_of(paint, alpha)
        if p is None:
            return
        self.cv.fill_polys(polys, False, self.cur_clip, p, alpha)

    def clip(self, path, m, evenodd):
        subs = R.flatten(path, m)
        polys = [p for p, _ in subs if len(p) >= 3]
        if not polys:
            self.cur_clip = R.Clip(self.cur_clip.x0, self.cur_clip.y0, self.cur_clip.x0, self.cur_clip.y0)
            return
        self.cur_clip = R.clip_to_path(self.cur_clip, polys, evenodd)

    def shade(self, sh, m, alpha):
        p = shading_paint(sh, m)
        if p is None:
            self.unsupported.add(f"shading type {sh.type}")
            return
        c = self.cur_clip
        self.cv.fill_polys([[(c.x0, c.y0), (c.x1, c.y0), (c.x1, c.y1), (c.x0, c.y1)]], False, c, p, alpha)

    # --- images
    def image(self, doc, stm, m, alpha, fill_rgb):
        try:
            img = decode_image(doc, stm, fill_rgb)
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"image skipped: {type(e).__name__}: {e}")
            return
        # device size of one source pixel
        sx = math.hypot(m[0], m[1])
        sy = math.hypot(m[2], m[3])
        k = int(min(img.w / max(sx, 1e-6), img.h / max(sy, 1e-6)))
        if k >= 2:
            img = shrink(img, k)
        inv = minv(m)
        if inv is None:
            return
        W, H = img.w, img.h
        rgb, al = img.rgb, img.alpha

        # poppler's rule: upscaling is bilinear below 400 %, nearest-neighbour (crisp pixels) from 400 % up
        smooth = (sx > W or sy > H) and sx < 4 * W and sy < 4 * H

        def paint(px, py):
            u = inv[0] * (px + 0.5) + inv[2] * (py + 0.5) + inv[4]
            v = inv[1] * (px + 0.5) + inv[3] * (py + 0.5) + inv[5]
            fx = u * W
            fy = (1 - v) * H
            if not smooth or W < 2 or H < 2 or img.stencil:
                ix = int(fx)
                iy = int(fy)
                ix = 0 if ix < 0 else W - 1 if ix >= W else ix
                iy = 0 if iy < 0 else H - 1 if iy >= H else iy
                i = iy * W + ix
                return (rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2], al[i] / 255.0 if al is not None else 1.0)
            fx -= 0.5
            fy -= 0.5
            x0 = int(math.floor(fx))
            y0 = int(math.floor(fy))
            tx = fx - x0
            ty = fy - y0
            x1 = x0 + 1
            y1 = y0 + 1
            x0 = 0 if x0 < 0 else W - 1 if x0 >= W else x0
            x1 = 0 if x1 < 0 else W - 1 if x1 >= W else x1
            y0 = 0 if y0 < 0 else H - 1 if y0 >= H else y0
            y1 = 0 if y1 < 0 else H - 1 if y1 >= H else y1
            i00, i10, i01, i11 = y0 * W + x0, y0 * W + x1, y1 * W + x0, y1 * W + x1
            w00, w10, w01, w11 = (1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty
            o = (rgb[3 * i00] * w00 + rgb[3 * i10] * w10 + rgb[3 * i01] * w01 + rgb[3 * i11] * w11,
                 rgb[3 * i00 + 1] * w00 + rgb[3 * i10 + 1] * w10 + rgb[3 * i01 + 1] * w01 + rgb[3 * i11 + 1] * w11,
                 rgb[3 * i00 + 2] * w00 + rgb[3 * i10 + 2] * w10 + rgb[3 * i01 + 2] * w01 + rgb[3 * i11 + 2] * w11)
            a = 1.0
            if al is not None:
                a = (al[i00] * w00 + al[i10] * w10 + al[i01] * w01 + al[i11] * w11) / 255.0
            return (o[0], o[1], o[2], a)
        quad = [apply(m, 0, 0), apply(m, 1, 0), apply(m, 1, 1), apply(m, 0, 1)]
        self.cv.fill_polys([quad], False, self.cur_clip, paint, alpha)

    # --- tiling patterns
    def _tiling_paint(self, paint):
        _, pat, m, rgb = paint
        d = pat.dict
        r = self.doc.resolve
        bbox = [float(r(v)) for v in r(d.get("BBox"))]
        xs, ys = float(r(d.get("XStep"))), float(r(d.get("YStep")))
        if xs == 0 or ys == 0:
            return None
        sc = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
        tw = max(1, min(2048, int(math.ceil(abs(xs) * sc))))
        th = max(1, min(2048, int(math.ceil(abs(ys) * sc))))
        key = (id(pat), tw, th, rgb)
        tiles = self._tile_cache.get(key)
        if tiles is None:
            tiles = []
            for bg in ((255, 255, 255), (0, 0, 0)):
                cv = R.Canvas(tw, th, bg)
                # pattern space -> tile pixels
                tm = (tw / abs(xs), 0, 0, -th / abs(ys), -bbox[0] * tw / abs(xs), th + bbox[1] * th / abs(ys))
                sub = Renderer(self.doc, cv, tm)
                sub.cur_clip = R.Clip(0, 0, tw, th)
                res = r(d.get("Resources"))
                it = Interpreter(self.doc, sub, res if isinstance(res, dict) else {}, tm, depth=8)
                if rgb is not None:
                    it.gs.fill_paint = it.gs.stroke_paint = ("rgb", rgb)
                    it.color_locked = True
                try:
                    it.run(self.doc.decode_stream(pat))
                except Exception as e:  # noqa: BLE001
                    self.doc.warnings.append(f"tiling pattern failed: {e}")
                tiles.append(cv)
            self._tile_cache[key] = tiles
        wcv, bcv = tiles
        inv = minv(m)
        if inv is None:
            return None
        x0, y0 = bbox[0], bbox[1]

        def paint_fn(px, py):
            u = inv[0] * (px + 0.5) + inv[2] * (py + 0.5) + inv[4]
            v = inv[1] * (px + 0.5) + inv[3] * (py + 0.5) + inv[5]
            fu = ((u - x0) / abs(xs)) % 1.0
            fv = ((v - y0) / abs(ys)) % 1.0
            tx = min(tw - 1, int(fu * tw))
            ty = min(th - 1, int((1 - fv) * th))
            i = 3 * tx
            wr, wg, wb = wcv.rows[ty][i:i + 3]
            br, bg_, bb = bcv.rows[ty][i:i + 3]
            a = 1.0 - (wr - br + wg - bg_ + wb - bb) / (3 * 255.0)
            if a <= 0.004:
                return (0, 0, 0, 0.0)
            return (min(255, br / a), min(255, bg_ / a), min(255, bb / a), a)
        return paint_fn


def render_page(doc, page, dpi=72.0, highlights=None, background=(255, 255, 255), annotations=True, use_crop=True):
    """Render a page dict to a Canvas. highlights: list of (x0,y0,x1,y1) user-space rects."""
    s = dpi / 72.0
    box = doc.page_box(page, use_crop)
    rot = doc.page_rotate(page)
    base, W, H = page_matrix(box, rot, s)
    if W * H > 60_000_000:
        raise ValueError(f"page would be {int(W)}x{int(H)} pixels; use a lower --dpi")
    cv = R.Canvas(max(1, int(math.ceil(W - 1e-6))), max(1, int(math.ceil(H - 1e-6))), background)
    dev = Renderer(doc, cv, base)
    res = doc.resolve(page.get("Resources"))
    data = doc.page_content(page)
    Interpreter(doc, dev, res if isinstance(res, dict) else {}, base, hidden_ocgs=hidden_ocgs(doc)).run(data)
    dev.cur_clip = R.Clip(0, 0, cv.w, cv.h)
    if annotations:
        _draw_annotations(doc, page, dev, base, res, hidden_ocgs(doc))
        dev.cur_clip = R.Clip(0, 0, cv.w, cv.h)
    for rect in highlights or []:
        x0, y0, x1, y1 = rect
        quad = [apply(base, x0, y0), apply(base, x1, y0), apply(base, x1, y1), apply(base, x0, y1)]
        cv.fill_polys([quad], False, dev.cur_clip, (255, 214, 0), 0.4)
    doc.render_unsupported = dev.unsupported
    return cv


def _draw_annotations(doc, page, dev, base, res, hidden):
    """Paint annotation appearance streams (/AP /N) the way viewers do: BBox*Matrix is fitted to /Rect."""
    r = doc.resolve
    annots = r(page.get("Annots"))
    if not isinstance(annots, list):
        return
    for aref in annots:
        a = r(aref)
        if not isinstance(a, dict) or str(r(a.get("Subtype"))) == "Popup":
            continue
        flags = int(r(a.get("F")) or 0)
        if flags & 2 or flags & 32:   # Hidden / NoView
            continue
        ap = r(a.get("AP"))
        n = r(ap.get("N")) if isinstance(ap, dict) else None
        if isinstance(n, dict):       # appearance states: pick /AS
            n = r(n.get(str(r(a.get("AS")) or "")))
        rect = r(a.get("Rect"))
        if not isinstance(n, Stream):
            if str(r(a.get("Subtype"))) == "Link" and isinstance(rect, list) and len(rect) == 4:
                _link_border(doc, a, rect, dev, base)
            continue
        if not isinstance(rect, list) or len(rect) != 4:
            continue
        try:
            rx0, ry0, rx1, ry1 = (float(r(v)) for v in rect)
            rx0, rx1 = sorted((rx0, rx1))
            ry0, ry1 = sorted((ry0, ry1))
            bb = [float(r(v)) for v in r(n.dict.get("BBox")) or [0, 0, 1, 1]]
            mt = tuple(float(r(v)) for v in r(n.dict.get("Matrix")) or IDENT)
            pts = [apply(mt, bb[0], bb[1]), apply(mt, bb[2], bb[1]), apply(mt, bb[2], bb[3]), apply(mt, bb[0], bb[3])]
            bx0, bx1 = min(p[0] for p in pts), max(p[0] for p in pts)
            by0, by1 = min(p[1] for p in pts), max(p[1] for p in pts)
            sx = (rx1 - rx0) / (bx1 - bx0) if bx1 > bx0 else 1.0
            sy = (ry1 - ry0) / (by1 - by0) if by1 > by0 else 1.0
            A = (sx, 0, 0, sy, rx0 - bx0 * sx, ry0 - by0 * sy)
            it = Interpreter(doc, dev, res if isinstance(res, dict) else {}, base, hidden_ocgs=hidden)
            it.gs.ctm = mmul(A, base)
            oc = a.get("OC")
            if oc is not None and it._oc_hidden(oc):
                continue
            dev.cur_clip = R.Clip(0, 0, dev.cv.w, dev.cv.h)
            it._form(n, aref if isinstance(aref, Ref) and False else n)
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"annotation skipped: {type(e).__name__}: {e}")


def _link_border(doc, a, rect, dev, base):
    """Links without an appearance stream show their /Border (or /BS) as a rectangle, as viewers do."""
    r = doc.resolve
    border = r(a.get("Border"))
    bs = r(a.get("BS"))
    width, dash = None, []
    if isinstance(bs, dict):
        width = float(r(bs.get("W", 1)))
        if str(r(bs.get("S")) or "S") == "D":
            dash = [float(r(v)) for v in r(bs.get("D")) or [3]]
    elif isinstance(border, list) and len(border) >= 3:
        width = float(r(border[2]))
        if len(border) > 3 and isinstance(r(border[3]), list):
            dash = [float(r(v)) for v in r(border[3])]
    if not width or width <= 0:
        return
    c = [float(r(v)) for v in r(a.get("C")) or [0, 0, 0]]
    rgb = (c[0],) * 3 if len(c) == 1 else tuple(c) if len(c) == 3 else cs.cmyk_to_rgb(*c) if len(c) == 4 else (0.0, 0.0, 0.0)
    x0, y0, x1, y1 = (float(r(v)) for v in rect)
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
    path = [("M", x0, y0), ("L", x1, y0), ("L", x1, y1), ("L", x0, y1), ("Z",)]  # centred on the Rect edge (as poppler)
    dev.cur_clip = R.Clip(0, 0, dev.cv.w, dev.cv.h)
    dev.stroke(path, base, {"w": width, "cap": 0, "join": 0, "miter": 10, "dash": (dash, 0.0)}, ("rgb", rgb), 1.0)
