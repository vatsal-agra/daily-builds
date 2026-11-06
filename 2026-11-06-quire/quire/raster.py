"""Anti-aliased scanline rasteriser, stroker, clip masks and PNG output. Pure Python.

Coverage model: SS sub-scanlines per pixel row, exact horizontal span coverage on each, winding
rule applied per sub-scanline (so self-overlapping non-zero paths are exact)."""
import math
import struct
import zlib

SS = 4


# ------------------------------------------------------------ flattening ----
def flatten(ops, m, tol=0.12):
    """Path ops (user space) + matrix -> list of (points, closed) in device space."""
    a, b, c, d, e, f = m
    subs = []
    cur = None
    start = None
    for op in ops:
        k = op[0]
        if k == "M":
            if cur is not None and len(cur) >= 1:
                subs.append((cur, False))
            x, y = op[1], op[2]
            p = (a * x + c * y + e, b * x + d * y + f)
            cur = [p]
            start = p
        elif k == "L":
            if cur is None:
                continue
            x, y = op[1], op[2]
            cur.append((a * x + c * y + e, b * x + d * y + f))
        elif k == "C":
            if cur is None:
                continue
            x0, y0 = cur[-1]
            x1, y1 = a * op[1] + c * op[2] + e, b * op[1] + d * op[2] + f
            x2, y2 = a * op[3] + c * op[4] + e, b * op[3] + d * op[4] + f
            x3, y3 = a * op[5] + c * op[6] + e, b * op[5] + d * op[6] + f
            dd = max(math.hypot(x0 - 2 * x1 + x2, y0 - 2 * y1 + y2), math.hypot(x1 - 2 * x2 + x3, y1 - 2 * y2 + y3))
            n = int(math.ceil(math.sqrt(0.75 * dd / tol))) if dd > 0 else 1
            n = max(1, min(n, 200))
            for i in range(1, n):
                t = i / n
                mt = 1 - t
                w0, w1, w2, w3 = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
                cur.append((w0 * x0 + w1 * x1 + w2 * x2 + w3 * x3, w0 * y0 + w1 * y1 + w2 * y2 + w3 * y3))
            cur.append((x3, y3))
        elif k == "Q":
            if cur is None:
                continue
            x0, y0 = cur[-1]
            x1, y1 = a * op[1] + c * op[2] + e, b * op[1] + d * op[2] + f
            x2, y2 = a * op[3] + c * op[4] + e, b * op[3] + d * op[4] + f
            dd = math.hypot(x0 - 2 * x1 + x2, y0 - 2 * y1 + y2)
            n = int(math.ceil(math.sqrt(0.25 * dd / tol))) if dd > 0 else 1
            n = max(1, min(n, 100))
            for i in range(1, n):
                t = i / n
                mt = 1 - t
                cur.append((mt * mt * x0 + 2 * mt * t * x1 + t * t * x2, mt * mt * y0 + 2 * mt * t * y1 + t * t * y2))
            cur.append((x2, y2))
        elif k == "Z":
            if cur is not None:
                subs.append((cur, True))
                cur = [start] if start is not None else None  # next segment implicitly restarts here
    if cur is not None and len(cur) >= 1:
        # drop a lone start-point left by 'Z'
        if not (len(cur) == 1 and subs and subs[-1][1] and subs[-1][0][0] == cur[0]):
            subs.append((cur, False))
    return subs


# --------------------------------------------------------------- stroker ----
def _circle(cx, cy, r, n=None):
    n = n or max(8, min(40, int(r * 3) + 8))
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def dash_polyline(pts, closed, dash, phase):
    """Split a polyline into dashes. Returns list of (points, closed=False)."""
    if closed:
        pts = pts + [pts[0]]
    arr = [v for v in dash]
    if len(arr) % 2:
        arr = arr * 2
    total = sum(arr)
    if total <= 1e-9 or any(v < 0 for v in arr):
        return [(pts, False)]
    length = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    if length / total * len(arr) > 200000:  # absurdly fine dash pattern: draw solid instead of hanging
        return [(pts, False)]
    idx = 0
    phase = phase % total if total else 0
    while phase >= arr[idx]:
        phase -= arr[idx]
        idx = (idx + 1) % len(arr)
    remain = arr[idx] - phase
    on = idx % 2 == 0
    out = []
    cur = [pts[0]] if on else None
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while seg - pos > remain:
            pos += remain
            t = pos / seg if seg else 0
            p = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            if on:
                cur.append(p)
                out.append((cur, False))
                cur = None
            else:
                cur = [p]
            on = not on
            idx = (idx + 1) % len(arr)
            remain = arr[idx]
            if remain <= 1e-9 and total > 0:
                # zero-length dash: emit a dot when 'on'
                if on:
                    out.append(([p, p], False))
                on = not on
                idx = (idx + 1) % len(arr)
                remain = arr[idx]
                if remain <= 1e-9:
                    break
        remain -= seg - pos
        if on and cur is not None:
            cur.append((x1, y1))
    if on and cur is not None and len(cur) > 1:
        out.append((cur, False))
    return out


def stroke_polygons(subpaths, width, cap, join, miter_limit):
    """subpaths: list of (points, closed) in *user space*. Returns list of polygons (user space),
    all with positive orientation so that non-zero fill = union."""
    hw = width / 2.0
    polys = []

    def add(poly):
        if len(poly) < 3:
            return
        area = 0.0
        for i in range(len(poly)):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % len(poly)]
            area += x0 * y1 - x1 * y0
        if area < 0:
            poly.reverse()
        polys.append(poly)

    for pts, closed in subpaths:
        # dedupe consecutive points
        q = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - q[-1][0]) > 1e-9 or abs(p[1] - q[-1][1]) > 1e-9:
                q.append(p)
        if closed and len(q) > 1 and abs(q[0][0] - q[-1][0]) < 1e-9 and abs(q[0][1] - q[-1][1]) < 1e-9:
            q.pop()
        if len(q) == 1:
            x, y = q[0]
            if cap == 1:
                add(_circle(x, y, hw))
            elif cap == 2 and (closed or True):
                add([(x - hw, y - hw), (x + hw, y - hw), (x + hw, y + hw), (x - hw, y + hw)])
            continue
        n = len(q)
        segs = n if closed else n - 1
        dirs = []
        for i in range(segs):
            x0, y0 = q[i]
            x1, y1 = q[(i + 1) % n]
            L = math.hypot(x1 - x0, y1 - y0)
            dirs.append(((x1 - x0) / L, (y1 - y0) / L))
        for i in range(segs):
            x0, y0 = q[i]
            x1, y1 = q[(i + 1) % n]
            ux, uy = dirs[i]
            nx, ny = -uy * hw, ux * hw
            ex0, ey0, ex1, ey1 = x0, y0, x1, y1
            if not closed and cap == 2:
                if i == 0:
                    ex0, ey0 = x0 - ux * hw, y0 - uy * hw
                if i == segs - 1:
                    ex1, ey1 = x1 + ux * hw, y1 + uy * hw
            add([(ex0 + nx, ey0 + ny), (ex1 + nx, ey1 + ny), (ex1 - nx, ey1 - ny), (ex0 - nx, ey0 - ny)])
        if not closed and cap == 1:
            add(_circle(q[0][0], q[0][1], hw))
            add(_circle(q[-1][0], q[-1][1], hw))
        # joins
        jr = range(segs) if closed else range(1, segs)
        for i in jr:
            p = q[i % n]
            d0 = dirs[(i - 1) % segs]
            d1 = dirs[i % segs]
            cross = d0[0] * d1[1] - d0[1] * d1[0]
            dot = d0[0] * d1[0] + d0[1] * d1[1]
            if abs(cross) < 1e-9 and dot > 0:
                continue
            if join == 1:
                add(_circle(p[0], p[1], hw))
                continue
            # outer side of the turn
            sgn = -1.0 if cross > 0 else 1.0
            n0 = (-d0[1] * hw * sgn, d0[0] * hw * sgn)
            n1 = (-d1[1] * hw * sgn, d1[0] * hw * sgn)
            a_ = (p[0] + n0[0], p[1] + n0[1])
            b_ = (p[0] + n1[0], p[1] + n1[1])
            if join == 0:
                # miter length / line width = 1 / sin(theta/2), theta = interior angle = pi - turn;
                # sin(theta/2) = cos(turn/2) = sqrt((1 + dot) / 2), dot = cos(turn)
                s2 = math.sqrt(max((1 + dot) / 2.0, 0.0))
                if s2 > 1e-9 and 1.0 / s2 <= miter_limit:
                    mx, my = n0[0] + n1[0], n0[1] + n1[1]
                    ml = math.hypot(mx, my)
                    if ml > 1e-12:
                        k = (hw / s2) / ml
                        tip = (p[0] + mx * k, p[1] + my * k)
                        add([p, a_, tip, b_])
                        continue
            add([p, a_, b_])  # bevel
    return polys


# ------------------------------------------------------------- scanlines ----
class Edge:
    __slots__ = ("ytop", "ybot", "x", "dxdy", "dir")

    def __init__(self, ytop, ybot, x, dxdy, d):
        self.ytop, self.ybot, self.x, self.dxdy, self.dir = ytop, ybot, x, dxdy, d


def build_edges(polys, ymin, ymax):
    edges = []
    for poly in polys:
        n = len(poly)
        if n < 2:
            continue
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            d = 1
            if y0 > y1:
                x0, y0, x1, y1 = x1, y1, x0, y0
                d = -1
            if y1 <= ymin or y0 >= ymax:
                continue
            edges.append(Edge(y0, y1, x0, (x1 - x0) / (y1 - y0), d))
            edges[-1].x = x0 - 0.0
    return edges


def scan(polys, evenodd, xmin, ymin, xmax, ymax, ss=SS):
    """Yield (y, runs) where runs = [(x0, x1, coverage)] covering pixel columns [x0, x1)."""
    if xmax <= xmin or ymax <= ymin:
        return
    edges = build_edges(polys, ymin, ymax)
    if not edges:
        return
    top = min(e.ytop for e in edges)
    bot = max(e.ybot for e in edges)
    ystart = max(ymin, int(math.floor(top)))
    yend = min(ymax, int(math.ceil(bot)))
    if yend <= ystart:
        return
    edges.sort(key=lambda e: e.ytop)
    ei = 0
    ne = len(edges)
    active = []
    W = xmax - xmin
    inv = 1.0 / ss
    for y in range(ystart, yend):
        acc = {}
        dif = {}
        any_ = False
        for s in range(ss):
            yc = y + (s + 0.5) * inv
            while ei < ne and edges[ei].ytop <= yc:
                active.append(edges[ei])
                ei += 1
            if not active:
                continue
            if any(e.ybot <= yc for e in active):
                active = [e for e in active if e.ybot > yc]
                if not active:
                    continue
            xs = sorted([(e.x + (yc - e.ytop) * e.dxdy, e.dir) for e in active])
            wind = 0
            sx = 0.0
            for x, d in xs:
                if evenodd:
                    inside_before = wind & 1
                    wind += 1
                    inside_after = wind & 1
                else:
                    inside_before = wind != 0
                    wind += d
                    inside_after = wind != 0
                if not inside_before and inside_after:
                    sx = x
                elif inside_before and not inside_after:
                    xa, xb = sx - xmin, x - xmin
                    if xb <= 0 or xa >= W:
                        continue
                    if xa < 0:
                        xa = 0.0
                    if xb > W:
                        xb = float(W)
                    if xb <= xa:
                        continue
                    ia, ib = int(xa), int(xb)
                    any_ = True
                    if ia == ib:
                        acc[ia] = acc.get(ia, 0.0) + (xb - xa) * inv
                    else:
                        acc[ia] = acc.get(ia, 0.0) + (ia + 1 - xa) * inv
                        if ib > ia + 1:
                            dif[ia + 1] = dif.get(ia + 1, 0.0) + inv
                            dif[ib] = dif.get(ib, 0.0) - inv
                        if xb > ib:
                            acc[ib] = acc.get(ib, 0.0) + (xb - ib) * inv
        if not any_:
            continue
        keys = sorted(set(acc) | set(dif))
        runs = []
        cur = 0.0
        prev = None
        for k in keys:
            if prev is not None and k > prev + 1 and cur > 1e-4:
                runs.append((prev + 1 + xmin, k + xmin, min(cur, 1.0)))
            cur += dif.get(k, 0.0)
            cv = cur + acc.get(k, 0.0)
            if cv > 1e-4 and k < W:
                runs.append((k + xmin, k + 1 + xmin, min(cv, 1.0)))
            prev = k
        if runs:
            yield y, runs


# ---------------------------------------------------------------- clip ----
class Clip:
    """Integer pixel rect + optional per-row coverage masks (bytearray 0..255 over rect width)."""
    __slots__ = ("x0", "y0", "x1", "y1", "mask")

    def __init__(self, x0, y0, x1, y1, mask=None):
        self.x0, self.y0, self.x1, self.y1, self.mask = x0, y0, x1, y1, mask

    def copy(self):
        return Clip(self.x0, self.y0, self.x1, self.y1, self.mask)

    def intersect_rect(self, x0, y0, x1, y1):
        nx0, ny0, nx1, ny1 = max(self.x0, x0), max(self.y0, y0), min(self.x1, x1), min(self.y1, y1)
        if nx1 < nx0:
            nx1 = nx0
        if ny1 < ny0:
            ny1 = ny0
        mask = None
        if self.mask is not None:
            mask = {y: row for y, row in self.mask.items() if ny0 <= y < ny1}
            return Clip(nx0, ny0, nx1, ny1, (mask, self.x0))
        return Clip(nx0, ny0, nx1, ny1, None)

    def row_mask(self, y):
        """Returns (bytearray over [self.x0, self.x1), or None) for row y."""
        if self.mask is None:
            return None
        masks, mx0 = self.mask
        row = masks.get(y)
        if row is None:
            return b""  # nothing visible
        return row


def clip_to_path(clip, polys, evenodd):
    """Intersect `clip` with a polygon set; returns new Clip."""
    # Axis-aligned rectangle fast path
    rect = _as_rect(polys)
    if rect is not None:
        x0, y0, x1, y1 = rect
        return clip.intersect_rect(int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))) if clip.mask is None else _mask_rect(clip, rect)
    xmin, ymin, xmax, ymax = clip.x0, clip.y0, clip.x1, clip.y1
    masks = {}
    old = clip.mask[0] if clip.mask else None
    ox0 = clip.mask[1] if clip.mask else 0
    bx0, by0, bx1, by1 = xmax, ymax, xmin, ymin
    for y, runs in scan(polys, evenodd, xmin, ymin, xmax, ymax):
        row = bytearray(xmax - xmin)
        any_ = False
        orow = old.get(y) if old is not None else None
        if old is not None and orow is None:
            continue
        for xa, xb, cv in runs:
            c = int(cv * 255 + 0.5)
            if c <= 0:
                continue
            if orow is None:
                row[xa - xmin:xb - xmin] = bytes([c]) * (xb - xa)
            else:
                for x in range(xa, xb):
                    row[x - xmin] = (orow[x - ox0] * c + 127) // 255 if 0 <= x - ox0 < len(orow) else 0
            any_ = True
            bx0, bx1 = min(bx0, xa), max(bx1, xb)
        if any_:
            masks[y] = row
            by0, by1 = min(by0, y), max(by1, y + 1)
    if not masks:
        return Clip(xmin, ymin, xmin, ymin, None)
    # tighten the rect; re-key masks relative to new x0 by keeping the old origin
    nc = Clip(max(xmin, bx0), max(ymin, by0), min(xmax, bx1), min(ymax, by1), (masks, xmin))
    return nc


def _mask_rect(clip, rect):
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    nc = clip.intersect_rect(x0, y0, x1, y1)
    return nc


def _as_rect(polys):
    if len(polys) != 1:
        return None
    p = polys[0]
    if len(p) == 5 and p[0] == p[4]:
        p = p[:4]
    if len(p) != 4:
        return None
    xs = sorted({round(q[0], 4) for q in p})
    ys = sorted({round(q[1], 4) for q in p})
    if len(xs) != 2 or len(ys) != 2:
        return None
    # must be a rectangle traversal: consecutive points share x or y
    for i in range(4):
        a, b = p[i], p[(i + 1) % 4]
        if abs(a[0] - b[0]) > 1e-4 and abs(a[1] - b[1]) > 1e-4:
            return None
    return xs[0], ys[0], xs[1], ys[1]


# --------------------------------------------------------------- canvas ----
class Canvas:
    def __init__(self, w, h, bg=(255, 255, 255)):
        self.w, self.h = w, h
        self.rows = [bytearray(bytes(bg) * w) for _ in range(h)]

    def fill_polys(self, polys, evenodd, clip, paint, alpha=1.0):
        """paint: (r,g,b) 0..255 ints, or callable (x, y) -> (r, g, b, a) with a in 0..1."""
        if clip.x1 <= clip.x0 or clip.y1 <= clip.y0:
            return
        for y, runs in scan(polys, evenodd, clip.x0, clip.y0, clip.x1, clip.y1):
            self.blend_runs(y, runs, clip, paint, alpha)

    def blend_runs(self, y, runs, clip, paint, alpha):
        row = self.rows[y]
        m = clip.row_mask(y)
        if m == b"":
            return
        mx0 = clip.mask[1] if clip.mask is not None else 0
        solid = isinstance(paint, tuple)
        if solid:
            r, g, b = paint
            pix = bytes((r, g, b))
        for xa, xb, cv in runs:
            a = cv * alpha
            if solid and m is None:
                if a >= 0.999:
                    row[3 * xa:3 * xb] = pix * (xb - xa)
                    continue
                ia = 1.0 - a
                sr, sg, sb = r * a, g * a, b * a
                for x in range(xa, xb):
                    i = 3 * x
                    row[i] = int(row[i] * ia + sr + 0.5)
                    row[i + 1] = int(row[i + 1] * ia + sg + 0.5)
                    row[i + 2] = int(row[i + 2] * ia + sb + 0.5)
                continue
            for x in range(xa, xb):
                aa = a
                if m is not None:
                    k = x - mx0
                    if not 0 <= k < len(m):
                        continue
                    aa *= m[k] / 255.0
                if solid:
                    sr, sg, sb = r, g, b
                else:
                    sr, sg, sb, sa = paint(x, y)
                    aa *= sa
                if aa <= 0.002:
                    continue
                i = 3 * x
                if aa >= 0.998:
                    row[i], row[i + 1], row[i + 2] = int(sr + 0.5), int(sg + 0.5), int(sb + 0.5)
                else:
                    row[i] = int(row[i] * (1 - aa) + sr * aa + 0.5)
                    row[i + 1] = int(row[i + 1] * (1 - aa) + sg * aa + 0.5)
                    row[i + 2] = int(row[i + 2] * (1 - aa) + sb * aa + 0.5)

    def to_png(self):
        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)

        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def read_png_rgb(data):
    """Minimal PNG reader (8-bit RGB/RGBA/gray, non-interlaced) for tests/compare tools. Returns (w,h,rows of bytes RGB)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    p = 8
    idat = b""
    w = h = ct = bd = 0
    while p < len(data):
        ln, t = struct.unpack(">I4s", data[p:p + 8])
        body = data[p + 8:p + 8 + ln]
        p += 12 + ln
        if t == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        elif t == b"IDAT":
            idat += body
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * ch
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        ft = raw[pos]
        row = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = row[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if ft == 1:
                row[i] = (row[i] + a) & 255
            elif ft == 2:
                row[i] = (row[i] + b) & 255
            elif ft == 3:
                row[i] = (row[i] + ((a + b) >> 1)) & 255
            elif ft == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = row
        if ch == 3:
            rows.append(bytes(row))
        elif ch == 4:
            rows.append(bytes(v for i in range(0, stride, 4) for v in row[i:i + 3]))
        elif ch == 1:
            rows.append(bytes(v for g in row for v in (g, g, g)))
        else:
            rows.append(bytes(v for i in range(0, stride, 2) for v in (row[i],) * 3))
    return w, h, rows
