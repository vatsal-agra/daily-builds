"""TrueType / OpenType (sfnt) parser: glyf outlines, cmap, hmtx, post names.
Outlines come back as path ops in font units: ('M',x,y) ('L',x,y) ('Q',cx,cy,x,y) ('C',...) ('Z',)."""
import struct


class FontError(Exception):
    pass


class TrueTypeFont:
    def __init__(self, data):
        self.data = data
        if data[:4] == b"ttcf":
            off = struct.unpack(">I", data[12:16])[0]
        else:
            off = 0
        tag = data[off:off + 4]
        if tag not in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"typ1"):
            raise FontError("not an sfnt font")
        n = struct.unpack(">H", data[off + 4:off + 6])[0]
        self.tables = {}
        for i in range(n):
            t, _, o, l = struct.unpack(">4sIII", data[off + 12 + 16 * i:off + 28 + 16 * i])
            self.tables[t.decode("latin-1")] = (o, l)
        self.is_cff = "CFF " in self.tables
        head = self._t("head")
        self.units_per_em = struct.unpack(">H", head[18:20])[0] if head else 1000
        self.units_per_em = self.units_per_em or 1000
        self.loca_fmt = struct.unpack(">h", head[50:52])[0] if head else 0
        maxp = self._t("maxp")
        self.num_glyphs = struct.unpack(">H", maxp[4:6])[0] if maxp else 0
        self._loca = None
        self._cmaps = None
        self._hmtx_n = 0
        hhea = self._t("hhea")
        if hhea:
            self._hmtx_n = struct.unpack(">H", hhea[34:36])[0]
        self._glyph_cache = {}
        self._post = None
        self._cff = None
        if self.is_cff:
            from .cff import CFFFont
            o, l = self.tables["CFF "]
            self._cff = CFFFont(data[o:o + l])
            if not self.num_glyphs:
                self.num_glyphs = len(self._cff.charstrings)

    def _t(self, name):
        if name not in self.tables:
            return None
        o, l = self.tables[name]
        return self.data[o:o + l]

    # ------------------------------------------------------------ metrics
    def advance(self, gid):
        h = self._t("hmtx")
        if not h or not self._hmtx_n:
            return None
        i = min(gid, self._hmtx_n - 1)
        if 4 * i + 2 > len(h):
            return None
        return struct.unpack(">H", h[4 * i:4 * i + 2])[0]

    # --------------------------------------------------------------- cmap
    def cmaps(self):
        if self._cmaps is not None:
            return self._cmaps
        self._cmaps = {}
        t = self._t("cmap")
        if not t or len(t) < 4:
            return self._cmaps
        n = struct.unpack(">H", t[2:4])[0]
        for i in range(n):
            pid, eid, off = struct.unpack(">HHI", t[4 + 8 * i:12 + 8 * i])
            try:
                self._cmaps[(pid, eid)] = self._parse_cmap(t, off)
            except (struct.error, IndexError):
                continue
        return self._cmaps

    @staticmethod
    def _parse_cmap(t, off):
        fmt = struct.unpack(">H", t[off:off + 2])[0]
        m = {}
        if fmt == 0:
            for c in range(256):
                g = t[off + 6 + c]
                if g:
                    m[c] = g
        elif fmt == 4:
            segx2 = struct.unpack(">H", t[off + 6:off + 8])[0]
            seg = segx2 // 2
            ends = struct.unpack(f">{seg}H", t[off + 14:off + 14 + segx2])
            starts = struct.unpack(f">{seg}H", t[off + 16 + segx2:off + 16 + 2 * segx2])
            deltas = struct.unpack(f">{seg}h", t[off + 16 + 2 * segx2:off + 16 + 3 * segx2])
            ro_pos = off + 16 + 3 * segx2
            ros = struct.unpack(f">{seg}H", t[ro_pos:ro_pos + segx2])
            for i in range(seg):
                for c in range(starts[i], ends[i] + 1):
                    if c == 0xFFFF:
                        continue
                    if ros[i] == 0:
                        g = (c + deltas[i]) & 0xFFFF
                    else:
                        p = ro_pos + 2 * i + ros[i] + 2 * (c - starts[i])
                        if p + 2 > len(t):
                            continue
                        g = struct.unpack(">H", t[p:p + 2])[0]
                        if g:
                            g = (g + deltas[i]) & 0xFFFF
                    if g:
                        m[c] = g
        elif fmt == 6:
            first, cnt = struct.unpack(">HH", t[off + 6:off + 10])
            for i in range(cnt):
                g = struct.unpack(">H", t[off + 10 + 2 * i:off + 12 + 2 * i])[0]
                if g:
                    m[first + i] = g
        elif fmt == 12:
            ng = struct.unpack(">I", t[off + 12:off + 16])[0]
            for i in range(ng):
                s, e, g = struct.unpack(">III", t[off + 16 + 12 * i:off + 28 + 12 * i])
                if e - s > 0x20000:
                    continue
                for c in range(s, e + 1):
                    m[c] = g + c - s
        return m

    def cmap_lookup(self, pid_eid, code):
        return self.cmaps().get(pid_eid, {}).get(code, 0)

    # --------------------------------------------------------- post names
    def glyph_names(self):
        if self._post is not None:
            return self._post
        self._post = {}
        t = self._t("post")
        if t and len(t) >= 34 and struct.unpack(">I", t[:4])[0] == 0x00020000:
            n = struct.unpack(">H", t[32:34])[0]
            idx = struct.unpack(f">{n}H", t[34:34 + 2 * n])
            names = []
            p = 34 + 2 * n
            while p < len(t):
                ln = t[p]
                names.append(t[p + 1:p + 1 + ln].decode("latin-1"))
                p += 1 + ln
            from .glyphlist import MAC_GLYPH_NAMES
            for gid, i in enumerate(idx):
                nm = MAC_GLYPH_NAMES[i] if i < 258 else (names[i - 258] if i - 258 < len(names) else None)
                if nm:
                    self._post.setdefault(nm, gid)
        if self._cff:
            for gid, nm in enumerate(self._cff.glyph_names):
                if nm:
                    self._post.setdefault(nm, gid)
        return self._post

    # ------------------------------------------------------------ outlines
    def _locas(self):
        if self._loca is None:
            t = self._t("loca") or b""
            n = self.num_glyphs + 1
            if self.loca_fmt == 0:
                n = min(n, len(t) // 2)
                self._loca = [2 * v for v in struct.unpack(f">{n}H", t[:2 * n])]
            else:
                n = min(n, len(t) // 4)
                self._loca = list(struct.unpack(f">{n}I", t[:4 * n]))
        return self._loca

    def glyph(self, gid, depth=0):
        """Path ops for glyph id, in font units."""
        if gid in self._glyph_cache:
            return self._glyph_cache[gid]
        if self._cff:
            ops = self._cff.glyph(gid)
        else:
            ops = self._glyf(gid, depth)
        self._glyph_cache[gid] = ops
        return ops

    def _glyf(self, gid, depth):
        if depth > 8:
            return []
        loca = self._locas()
        if gid < 0 or gid + 1 >= len(loca):
            return []
        a, b = loca[gid], loca[gid + 1]
        if b <= a:
            return []
        go, gl = self.tables.get("glyf", (0, 0))
        d = self.data[go + a:go + b]
        if len(d) < 10:
            return []
        nc = struct.unpack(">h", d[:2])[0]
        if nc >= 0:
            return self._simple(d, nc)
        return self._composite(d, depth)

    @staticmethod
    def _simple(d, nc):
        if nc == 0:
            return []
        ends = struct.unpack(f">{nc}H", d[10:10 + 2 * nc])
        npts = ends[-1] + 1
        p = 10 + 2 * nc
        il = struct.unpack(">H", d[p:p + 2])[0]
        p += 2 + il
        flags = []
        while len(flags) < npts:
            f = d[p]
            p += 1
            flags.append(f)
            if f & 8:
                r = d[p]
                p += 1
                flags.extend([f] * r)
        flags = flags[:npts]
        xs, ys = [], []
        v = 0
        for f in flags:
            if f & 2:
                dx = d[p]
                p += 1
                v += dx if f & 16 else -dx
            elif not f & 16:
                v += struct.unpack(">h", d[p:p + 2])[0]
                p += 2
            xs.append(v)
        v = 0
        for f in flags:
            if f & 4:
                dy = d[p]
                p += 1
                v += dy if f & 32 else -dy
            elif not f & 32:
                v += struct.unpack(">h", d[p:p + 2])[0]
                p += 2
            ys.append(v)
        ops = []
        start = 0
        for e in ends:
            pts = [(xs[i], ys[i], flags[i] & 1) for i in range(start, e + 1)]
            start = e + 1
            ops += TrueTypeFont._contour(pts)
        return ops

    @staticmethod
    def _contour(pts):
        n = len(pts)
        if n == 0:
            return []
        # find a starting on-curve point (or synthesise one)
        si = next((i for i, p in enumerate(pts) if p[2]), None)
        if si is None:
            sx = (pts[0][0] + pts[-1][0]) / 2
            sy = (pts[0][1] + pts[-1][1]) / 2
            seq = pts
        else:
            sx, sy = pts[si][0], pts[si][1]
            seq = pts[si + 1:] + pts[:si]
        ops = [("M", sx, sy)]
        cx = cy = None
        for x, y, on in seq:
            if on:
                if cx is None:
                    ops.append(("L", x, y))
                else:
                    ops.append(("Q", cx, cy, x, y))
                    cx = cy = None
            else:
                if cx is not None:
                    mx, my = (cx + x) / 2, (cy + y) / 2
                    ops.append(("Q", cx, cy, mx, my))
                cx, cy = x, y
        if cx is not None:
            ops.append(("Q", cx, cy, sx, sy))
        ops.append(("Z",))
        return ops

    def _composite(self, d, depth):
        p = 10
        ops = []
        while True:
            flags, gi = struct.unpack(">HH", d[p:p + 4])
            p += 4
            if flags & 1:
                a1, a2 = struct.unpack(">hh", d[p:p + 4])
                p += 4
            else:
                a1, a2 = struct.unpack(">bb", d[p:p + 2])
                p += 2
            sx = sy = 1.0
            s01 = s10 = 0.0
            if flags & 8:
                sx = sy = struct.unpack(">h", d[p:p + 2])[0] / 16384
                p += 2
            elif flags & 0x40:
                sx, sy = (v / 16384 for v in struct.unpack(">hh", d[p:p + 4]))
                p += 4
            elif flags & 0x80:
                sx, s01, s10, sy = (v / 16384 for v in struct.unpack(">hhhh", d[p:p + 8]))
                p += 8
            dx, dy = (a1, a2) if flags & 2 else (0, 0)
            sub = self._glyf(gi, depth + 1)
            for op in sub:
                if op[0] == "Z":
                    ops.append(op)
                    continue
                pts = []
                for i in range(1, len(op), 2):
                    x, y = op[i], op[i + 1]
                    pts += [sx * x + s10 * y + dx, s01 * x + sy * y + dy]
                ops.append((op[0], *pts))
            if not flags & 0x20:
                break
        return ops
