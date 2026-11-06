"""Adobe Type 1 font programs (PFA/PFB/PDF FontFile): eexec decryption, charstring interpreter."""
import re
import struct


class Type1Error(Exception):
    pass


def _decrypt(data, r, n):
    out = bytearray()
    for c in data:
        out.append(c ^ (r >> 8))
        r = ((c + r) * 52845 + 22719) & 0xFFFF
    return bytes(out[n:])


def _strip_pfb(data):
    if data[:1] != b"\x80":
        return data
    out = bytearray()
    p = 0
    while p + 6 <= len(data) and data[p] == 0x80:
        t = data[p + 1]
        if t == 3:
            break
        ln = struct.unpack("<I", data[p + 2:p + 6])[0]
        out += data[p + 6:p + 6 + ln]
        p += 6 + ln
    return bytes(out)


class Type1Font:
    def __init__(self, data):
        data = _strip_pfb(data)
        i = data.find(b"eexec")
        if i < 0:
            raise Type1Error("no eexec section")
        clear = data[:i]
        j = i + 5
        while j < len(data) and data[j] in b" \t\r\n":
            j += 1
        enc = data[j:]
        head = enc[:4]
        if len(head) == 4 and all(c in b"0123456789abcdefABCDEF" for c in head):
            hexd = re.sub(rb"[^0-9a-fA-F]", b"", enc)
            hexd = hexd[:len(hexd) // 2 * 2]
            enc = bytes.fromhex(hexd.decode())
        priv = _decrypt(enc, 55665, 4)
        m = re.search(rb"/FontMatrix\s*\[([^\]]*)\]", clear)
        self.matrix = [float(v) for v in m.group(1).split()] if m else [0.001, 0, 0, 0.001, 0, 0]
        if len(self.matrix) != 6 or not self.matrix[0]:
            self.matrix = [0.001, 0, 0, 0.001, 0, 0]
        self.encoding = self._encoding(clear)
        m = re.search(rb"/lenIV\s+(-?\d+)", priv)
        self.leniv = int(m.group(1)) if m else 4
        self.subrs = {}
        self.charstrings = {}
        self._parse_private(priv)
        self._cache = {}
        self._adv = {}

    @staticmethod
    def _encoding(clear):
        enc = {}
        if re.search(rb"/Encoding\s+StandardEncoding\s+def", clear):
            from .glyphlist import STANDARD, unicode_to_name
            return {c: unicode_to_name(u) for c, u in STANDARD.items()}
        for m in re.finditer(rb"dup\s+(\d+)\s*/([^\s/\[\]{}()<>]+)\s+put", clear):
            enc[int(m.group(1))] = m.group(2).decode("latin-1")
        return enc

    def _parse_private(self, d):
        # tokens like:  dup 5 23 RD <23 bytes> NP    and    /name 45 RD <45 bytes> ND
        for m in re.finditer(rb"dup\s+(\d+)\s+(\d+)\s+(RD|-\|)\s", d):
            n, ln = int(m.group(1)), int(m.group(2))
            s = m.end()
            self.subrs[n] = self._dc(d[s:s + ln])
        cs = d.find(b"/CharStrings")
        if cs < 0:
            raise Type1Error("no CharStrings")
        p = cs
        pat = re.compile(rb"/([^\s/\[\]{}()<>]+)\s+(\d+)\s+(RD|-\|)\s")
        while True:
            m = pat.search(d, p)
            if not m:
                break
            ln = int(m.group(2))
            s = m.end()
            self.charstrings[m.group(1).decode("latin-1")] = self._dc(d[s:s + ln])
            p = s + ln
        if not self.charstrings:
            raise Type1Error("empty CharStrings")

    def _dc(self, b):
        if self.leniv < 0:
            return b
        return _decrypt(b, 4330, self.leniv)

    # ---------------------------------------------------------- outlines
    def advance(self, name):
        if name not in self._adv:
            self.outline(name, 1.0)
        return self._adv.get(name, 0)

    def outline(self, name, scale):
        key = (name, scale)
        if key in self._cache:
            return self._cache[key]
        cs = self.charstrings.get(name)
        if cs is None:
            return []
        it = _T1Interp(self)
        try:
            it.run(cs, 0)
        except (IndexError, ValueError, RecursionError, struct.error, KeyError):
            pass
        if it.open:
            it.ops.append(("Z",))
        self._adv[name] = it.wx
        ops = []
        for op in it.ops:
            ops.append((op[0],) + tuple(v * scale for v in op[1:]))
        self._cache[key] = ops
        return ops


class _T1Interp:
    def __init__(self, font):
        self.f = font
        self.st = []
        self.ps = []
        self.ops = []
        self.x = self.y = 0.0
        self.sbx = self.sby = 0.0
        self.wx = 0
        self.open = False
        self.flex = False
        self.flex_pts = []
        self.done = False

    def _move(self, dx, dy):
        self.x += dx
        self.y += dy
        if self.flex:
            self.flex_pts.append((self.x, self.y))
            return
        if self.open:
            self.ops.append(("Z",))
        self.ops.append(("M", self.x, self.y))
        self.open = True

    def _line(self, dx, dy):
        if not self.open:
            self.ops.append(("M", self.x, self.y))
            self.open = True
        self.x += dx
        self.y += dy
        self.ops.append(("L", self.x, self.y))

    def _curve(self, a, b, c, d, e, f):
        if not self.open:
            self.ops.append(("M", self.x, self.y))
            self.open = True
        x1, y1 = self.x + a, self.y + b
        x2, y2 = x1 + c, y1 + d
        self.x, self.y = x2 + e, y2 + f
        self.ops.append(("C", x1, y1, x2, y2, self.x, self.y))

    def run(self, cs, depth):
        if depth > 12:
            return
        st = self.st
        i, n = 0, len(cs)
        while i < n and not self.done:
            b = cs[i]
            i += 1
            if b >= 32:
                if b <= 246:
                    st.append(b - 139)
                elif b <= 250:
                    st.append((b - 247) * 256 + cs[i] + 108)
                    i += 1
                elif b <= 254:
                    st.append(-(b - 251) * 256 - cs[i] - 108)
                    i += 1
                else:
                    st.append(struct.unpack(">i", cs[i:i + 4])[0])
                    i += 4
                continue
            if b == 13:  # hsbw
                self.sbx, self.wx = st[0], st[1]
                self.x, self.y = self.sbx, 0.0
                st.clear()
            elif b == 21:
                self._move(st[-2], st[-1]); st.clear()
            elif b == 22:
                self._move(st[-1], 0); st.clear()
            elif b == 4:
                self._move(0, st[-1]); st.clear()
            elif b == 5:
                self._line(st[0], st[1]); st.clear()
            elif b == 6:
                self._line(st[0], 0); st.clear()
            elif b == 7:
                self._line(0, st[0]); st.clear()
            elif b == 8:
                self._curve(*st[:6]); st.clear()
            elif b == 30:  # vhcurveto
                self._curve(0, st[0], st[1], st[2], st[3], 0); st.clear()
            elif b == 31:  # hvcurveto
                self._curve(st[0], 0, st[1], st[2], 0, st[3]); st.clear()
            elif b == 9:  # closepath
                if self.open:
                    self.ops.append(("Z",))
                    self.open = False
                st.clear()
            elif b == 10:  # callsubr
                num = int(st.pop())
                sub = self.f.subrs.get(num)
                if sub is not None:
                    self.run(sub, depth + 1)
            elif b == 11:
                return
            elif b == 14:
                self.done = True
                return
            elif b in (1, 3):
                st.clear()
            elif b == 12:
                b2 = cs[i]
                i += 1
                if b2 == 7:  # sbw
                    self.sbx, self.wx = st[0], st[2]
                    self.x, self.y = st[0], st[1]
                    st.clear()
                elif b2 == 12:  # div
                    d, a = st.pop(), st.pop()
                    st.append(a / d if d else 0)
                elif b2 == 16:  # callothersubr
                    osn = int(st.pop())
                    na = int(st.pop())
                    args = [st.pop() for _ in range(na)] if na else []
                    self._othersubr(osn, args)
                elif b2 == 17:  # pop
                    st.append(self.ps.pop() if self.ps else 0)
                elif b2 == 33:  # setcurrentpoint
                    self.x, self.y = st[-2], st[-1]
                    st.clear()
                elif b2 == 6:  # seac
                    asb, adx, ady, bchar, achar = st[:5]
                    st.clear()
                    self._seac(asb, adx, ady, int(bchar), int(achar))
                    self.done = True
                    return
                else:  # dotsection, vstem3, hstem3
                    st.clear()
            else:
                st.clear()

    def _othersubr(self, n, args):
        if n == 1:
            self.flex = True
            self.flex_pts = []
        elif n == 2:
            pass
        elif n == 0:
            self.flex = False
            pts = self.flex_pts
            if len(pts) >= 7:
                if not self.open:
                    self.ops.append(("M", pts[0][0], pts[0][1]))
                    self.open = True
                self.ops.append(("C", pts[1][0], pts[1][1], pts[2][0], pts[2][1], pts[3][0], pts[3][1]))
                self.ops.append(("C", pts[4][0], pts[4][1], pts[5][0], pts[5][1], pts[6][0], pts[6][1]))
                self.x, self.y = pts[6]
            # args = [flex_height, x, y] pushed in reverse; results returned through 'pop pop'
            self.ps = [self.y, self.x]
        elif n == 3:
            self.ps = [args[0] if args else 3]
        else:
            self.ps = list(args)

    def _seac(self, asb, adx, ady, bchar, achar):
        from .glyphlist import STANDARD, unicode_to_name
        if self.open:
            self.ops.append(("Z",))
            self.open = False
        wx, sbx = self.wx, self.sbx
        for ch, dx, dy in ((bchar, 0, 0), (achar, sbx - asb + adx, ady)):
            u = STANDARD.get(ch)
            nm = unicode_to_name(u) if u else None
            cs = self.f.charstrings.get(nm)
            if cs is None:
                continue
            sub = _T1Interp(self.f)
            try:
                sub.run(cs, 1)
            except (IndexError, ValueError, struct.error):
                pass
            if sub.open:
                sub.ops.append(("Z",))
            for op in sub.ops:
                if op[0] == "Z":
                    self.ops.append(op)
                else:
                    pts = []
                    for k in range(1, len(op), 2):
                        pts += [op[k] + dx, op[k + 1] + dy]
                    self.ops.append((op[0], *pts))
        self.wx = wx
