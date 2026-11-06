"""CFF (Compact Font Format) parser and Type 2 charstring interpreter."""
import struct

_STD = ("space exclam quotedbl numbersign dollar percent ampersand quoteright parenleft parenright asterisk plus comma "
        "hyphen period slash zero one two three four five six seven eight nine colon semicolon less equal greater "
        "question at A B C D E F G H I J K L M N O P Q R S T U V W X Y Z bracketleft backslash bracketright "
        "asciicircum underscore quoteleft a b c d e f g h i j k l m n o p q r s t u v w x y z braceleft bar "
        "braceright asciitilde exclamdown cent sterling fraction yen florin section currency quotesingle "
        "quotedblleft guillemotleft guilsinglleft guilsinglright fi fl endash dagger daggerdbl periodcentered "
        "paragraph bullet quotesinglbase quotedblbase quotedblright guillemotright ellipsis perthousand "
        "questiondown grave acute circumflex tilde macron breve dotaccent dieresis ring cedilla hungarumlaut "
        "ogonek caron emdash AE ordfeminine Lslash Oslash OE ordmasculine ae dotlessi lslash oslash oe germandbls "
        "onesuperior logicalnot mu trademark Eth onehalf plusminus Thorn onequarter divide brokenbar degree thorn "
        "threequarters twosuperior registered minus eth multiply threesuperior copyright Aacute Acircumflex "
        "Adieresis Agrave Aring Atilde Ccedilla Eacute Ecircumflex Edieresis Egrave Iacute Icircumflex Idieresis "
        "Igrave Ntilde Oacute Ocircumflex Odieresis Ograve Otilde Scaron Uacute Ucircumflex Udieresis Ugrave "
        "Yacute Ydieresis Zcaron aacute acircumflex adieresis agrave aring atilde ccedilla eacute ecircumflex "
        "edieresis egrave iacute icircumflex idieresis igrave ntilde oacute ocircumflex odieresis ograve otilde "
        "scaron uacute ucircumflex udieresis ugrave yacute ydieresis zcaron").split()
STD_STRINGS = [".notdef"] + _STD  # SID 0..228


class CFFError(Exception):
    pass


def _index(d, p):
    cnt = struct.unpack(">H", d[p:p + 2])[0]
    if cnt == 0:
        return [], p + 2
    osz = d[p + 2]
    offs = [int.from_bytes(d[p + 3 + i * osz:p + 3 + (i + 1) * osz], "big") for i in range(cnt + 1)]
    base = p + 3 + (cnt + 1) * osz - 1
    return [d[base + offs[i]:base + offs[i + 1]] for i in range(cnt)], base + offs[-1]


def _dict(d):
    out = {}
    ops = []
    i = 0
    n = len(d)
    while i < n:
        b = d[i]
        if b <= 21:
            if b == 12:
                b = 1200 + d[i + 1]
                i += 1
            out[b] = ops
            ops = []
            i += 1
        elif b == 28:
            ops.append(struct.unpack(">h", d[i + 1:i + 3])[0])
            i += 3
        elif b == 29:
            ops.append(struct.unpack(">i", d[i + 1:i + 5])[0])
            i += 5
        elif b == 30:
            s = ""
            i += 1
            done = False
            while not done and i < n:
                for nib in (d[i] >> 4, d[i] & 15):
                    if nib < 10:
                        s += str(nib)
                    elif nib == 10:
                        s += "."
                    elif nib == 11:
                        s += "E"
                    elif nib == 12:
                        s += "E-"
                    elif nib == 14:
                        s += "-"
                    elif nib == 15:
                        done = True
                        break
                i += 1
            try:
                ops.append(float(s))
            except ValueError:
                ops.append(0.0)
        elif 32 <= b <= 246:
            ops.append(b - 139)
            i += 1
        elif 247 <= b <= 250:
            ops.append((b - 247) * 256 + d[i + 1] + 108)
            i += 2
        elif 251 <= b <= 254:
            ops.append(-(b - 251) * 256 - d[i + 1] - 108)
            i += 2
        else:
            i += 1
    return out


def _bias(n):
    return 107 if n < 1240 else 1131 if n < 33900 else 32768


class CFFFont:
    def __init__(self, data):
        self.data = data
        hdr = data[2]
        names, p = _index(data, hdr)
        tops, p = _index(data, p)
        strings, p = _index(data, p)
        self.gsubrs, p = _index(data, p)
        self.strings = [s.decode("latin-1") for s in strings]
        top = _dict(tops[0])
        self.top = top
        self.matrix = top.get(1207, [0.001, 0, 0, 0.001, 0, 0])
        self.charstrings, _ = _index(data, int(top[17][0]))
        ng = len(self.charstrings)
        self.is_cid = 1230 in top
        self.charset = self._read_charset(int(top.get(15, [0])[0]), ng)
        self.glyph_names = [self._sid(s) if not self.is_cid else "" for s in self.charset]
        self.name_to_gid = {n: g for g, n in enumerate(self.glyph_names) if n}
        self.cid_to_gid = {c: g for g, c in enumerate(self.charset)} if self.is_cid else {}
        self.privs = []
        self.fdselect = None
        if self.is_cid:
            fds, _ = _index(data, int(top[1236][0]))
            for fd in fds:
                self.privs.append(self._private(_dict(fd)))
            self.fdselect = self._read_fdselect(int(top[1237][0]), ng)
        else:
            self.privs.append(self._private(top))
        self.builtin_encoding = None
        if not self.is_cid:
            self.builtin_encoding = self._read_encoding(int(top.get(16, [0])[0]))
        self._cache = {}

    def _sid(self, sid):
        if sid < len(STD_STRINGS):
            return STD_STRINGS[sid]
        i = sid - 391
        return self.strings[i] if 0 <= i < len(self.strings) else ""

    def _private(self, d):
        if 18 not in d:
            return {"subrs": [], "dw": 0, "nw": 0}
        size, off = int(d[18][0]), int(d[18][1])
        pd = _dict(self.data[off:off + size])
        subrs = []
        if 19 in pd:
            subrs, _ = _index(self.data, off + int(pd[19][0]))
        return {"subrs": subrs, "dw": pd.get(20, [0])[0], "nw": pd.get(21, [0])[0]}

    def _read_charset(self, off, ng):
        if off <= 2:
            # predefined charsets: ISOAdobe = SID i for gid i
            return list(range(ng))
        d = self.data
        fmt = d[off]
        out = [0]
        p = off + 1
        if fmt == 0:
            for _ in range(ng - 1):
                out.append(struct.unpack(">H", d[p:p + 2])[0])
                p += 2
        else:
            while len(out) < ng:
                first = struct.unpack(">H", d[p:p + 2])[0]
                if fmt == 1:
                    left = d[p + 2]
                    p += 3
                else:
                    left = struct.unpack(">H", d[p + 2:p + 4])[0]
                    p += 4
                out.extend(range(first, first + left + 1))
        return out[:ng]

    def _read_fdselect(self, off, ng):
        d = self.data
        fmt = d[off]
        if fmt == 0:
            return list(d[off + 1:off + 1 + ng])
        n = struct.unpack(">H", d[off + 1:off + 3])[0]
        out = [0] * ng
        rng = [struct.unpack(">HB", d[off + 3 + 3 * i:off + 6 + 3 * i]) for i in range(n)]
        sentinel = struct.unpack(">H", d[off + 3 + 3 * n:off + 5 + 3 * n])[0]
        for i, (first, fd) in enumerate(rng):
            end = rng[i + 1][0] if i + 1 < n else sentinel
            for g in range(first, min(end, ng)):
                out[g] = fd
        return out

    def _read_encoding(self, off):
        if off <= 1:
            return None  # Standard / Expert -> caller's default
        d = self.data
        fmt = d[off] & 0x7F
        enc = {}
        p = off + 1
        if fmt == 0:
            n = d[p]
            for i in range(n):
                enc[d[p + 1 + i]] = i + 1
        elif fmt == 1:
            n = d[p]
            gid = 1
            for i in range(n):
                first, left = d[p + 1 + 2 * i], d[p + 2 + 2 * i]
                for c in range(first, first + left + 1):
                    enc[c] = gid
                    gid += 1
        return enc

    # --------------------------------------------------------- charstrings
    def glyph(self, gid):
        if gid in self._cache:
            return self._cache[gid]
        if gid < 0 or gid >= len(self.charstrings):
            return []
        fd = self.fdselect[gid] if self.fdselect else 0
        priv = self.privs[fd] if fd < len(self.privs) else self.privs[0]
        try:
            ops = _Interp(self, priv).run(self.charstrings[gid])
        except (IndexError, ValueError, RecursionError, struct.error):
            ops = []
        self._cache[gid] = ops
        return ops

    def width_info(self, gid):
        return None


class _Interp:
    def __init__(self, font, priv):
        self.f = font
        self.priv = priv
        self.st = []
        self.ops = []
        self.x = self.y = 0.0
        self.nhints = 0
        self.open = False
        self.have_width = False
        self.done = False
        self.trans = [0.0] * 32

    def run(self, cs):
        self.exec(cs, 0)
        if self.open:
            self.ops.append(("Z",))
        return self.ops

    def _width(self, expect_even_args):
        # first stack-clearing op may carry an extra width arg
        if not self.have_width:
            self.have_width = True
            return True
        return False

    def _chk(self, n_expected=None, even=False):
        if self.have_width:
            return
        self.have_width = True
        if n_expected is not None:
            if len(self.st) > n_expected:
                self.st.pop(0)
        elif even:
            if len(self.st) % 2:
                self.st.pop(0)

    def moveto(self, dx, dy):
        if self.open:
            self.ops.append(("Z",))
        self.x += dx
        self.y += dy
        self.ops.append(("M", self.x, self.y))
        self.open = True

    def lineto(self, dx, dy):
        self.x += dx
        self.y += dy
        self.ops.append(("L", self.x, self.y))

    def curveto(self, a, b, c, d, e, f):
        x1, y1 = self.x + a, self.y + b
        x2, y2 = x1 + c, y1 + d
        self.x, self.y = x2 + e, y2 + f
        self.ops.append(("C", x1, y1, x2, y2, self.x, self.y))

    def exec(self, cs, depth):
        if depth > 12:
            return
        i, n = 0, len(cs)
        st = self.st
        while i < n and not self.done:
            b = cs[i]
            i += 1
            if b >= 32 or b == 28:
                if b == 28:
                    st.append(struct.unpack(">h", cs[i:i + 2])[0])
                    i += 2
                elif b <= 246:
                    st.append(b - 139)
                elif b <= 250:
                    st.append((b - 247) * 256 + cs[i] + 108)
                    i += 1
                elif b <= 254:
                    st.append(-(b - 251) * 256 - cs[i] - 108)
                    i += 1
                else:
                    st.append(struct.unpack(">i", cs[i:i + 4])[0] / 65536)
                    i += 4
                continue
            if b in (1, 3, 18, 23):  # hstem vstem hstemhm vstemhm
                self._chk(even=True)
                self.nhints += len(st) // 2
                st.clear()
            elif b in (19, 20):  # hintmask cntrmask
                self._chk(even=True)
                self.nhints += len(st) // 2
                st.clear()
                i += (self.nhints + 7) // 8
            elif b == 21:
                self._chk(2)
                self.moveto(st[-2], st[-1])
                st.clear()
            elif b == 22:
                self._chk(1)
                self.moveto(st[-1], 0)
                st.clear()
            elif b == 4:
                self._chk(1)
                self.moveto(0, st[-1])
                st.clear()
            elif b == 5:
                for k in range(0, len(st) - 1, 2):
                    self.lineto(st[k], st[k + 1])
                st.clear()
            elif b in (6, 7):
                horiz = b == 6
                for v in st:
                    self.lineto(v, 0) if horiz else self.lineto(0, v)
                    horiz = not horiz
                st.clear()
            elif b == 8:
                for k in range(0, len(st) - 5, 6):
                    self.curveto(*st[k:k + 6])
                st.clear()
            elif b == 24:  # rcurveline
                k = 0
                while k + 6 <= len(st) - 2:
                    self.curveto(*st[k:k + 6])
                    k += 6
                self.lineto(st[k], st[k + 1])
                st.clear()
            elif b == 25:  # rlinecurve
                k = 0
                while k + 2 <= len(st) - 6:
                    self.lineto(st[k], st[k + 1])
                    k += 2
                self.curveto(*st[k:k + 6])
                st.clear()
            elif b == 26:  # vvcurveto
                k = 0
                dx1 = 0
                if len(st) % 4:
                    dx1 = st[0]
                    k = 1
                while k + 4 <= len(st):
                    self.curveto(dx1, st[k], st[k + 1], st[k + 2], 0, st[k + 3])
                    dx1 = 0
                    k += 4
                st.clear()
            elif b == 27:  # hhcurveto
                k = 0
                dy1 = 0
                if len(st) % 4:
                    dy1 = st[0]
                    k = 1
                while k + 4 <= len(st):
                    self.curveto(st[k], dy1, st[k + 1], st[k + 2], st[k + 3], 0)
                    dy1 = 0
                    k += 4
                st.clear()
            elif b in (30, 31):  # vhcurveto hvcurveto
                horiz = b == 31
                k = 0
                while k + 4 <= len(st):
                    last = (len(st) - k == 5)
                    ex = st[k + 4] if last else 0
                    if horiz:
                        self.curveto(st[k], 0, st[k + 1], st[k + 2], ex, st[k + 3])
                    else:
                        self.curveto(0, st[k], st[k + 1], st[k + 2], st[k + 3], ex)
                    horiz = not horiz
                    k += 4
                st.clear()
            elif b == 10:  # callsubr
                subrs = self.priv["subrs"]
                idx = int(st.pop()) + _bias(len(subrs))
                if 0 <= idx < len(subrs):
                    self.exec(subrs[idx], depth + 1)
            elif b == 29:  # callgsubr
                subrs = self.f.gsubrs
                idx = int(st.pop()) + _bias(len(subrs))
                if 0 <= idx < len(subrs):
                    self.exec(subrs[idx], depth + 1)
            elif b == 11:  # return
                return
            elif b == 14:  # endchar (possibly seac)
                self._chk(4 if len(st) >= 4 else None) if len(st) in (1, 5) else None
                if len(st) >= 4:
                    adx, ady, bchar, achar = st[-4:]
                    self._seac(adx, ady, int(bchar), int(achar))
                self.done = True
                return
            elif b == 12:
                b2 = cs[i]
                i += 1
                self._escape(b2)
            else:
                st.clear()

    def _seac(self, adx, ady, bchar, achar):
        if self.open:
            self.ops.append(("Z",))
            self.open = False
        names = {v: k for k, v in enumerate(self.f.glyph_names)}
        from .glyphlist import STANDARD, unicode_to_name
        for ch, dx, dy in ((bchar, 0, 0), (achar, adx, ady)):
            u = STANDARD.get(ch)
            gid = names.get(unicode_to_name(u)) if u else None
            if gid is None:
                continue
            for op in self.f.glyph(gid):
                if op[0] == "Z":
                    self.ops.append(op)
                else:
                    pts = []
                    for k in range(1, len(op), 2):
                        pts += [op[k] + dx, op[k + 1] + dy]
                    self.ops.append((op[0], *pts))

    def _escape(self, b2):
        st = self.st
        if b2 == 35:  # flex
            self.curveto(*st[0:6])
            self.curveto(*st[6:12])
            st.clear()
        elif b2 == 34:  # hflex
            d = st
            self.curveto(d[0], 0, d[1], d[2], d[3], 0)
            self.curveto(d[4], 0, d[5], -d[2], d[6], 0)
            st.clear()
        elif b2 == 36:  # hflex1
            d = st
            self.curveto(d[0], d[1], d[2], d[3], d[4], 0)
            self.curveto(d[5], 0, d[6], d[7], d[8], -(d[1] + d[3] + d[7]))
            st.clear()
        elif b2 == 37:  # flex1
            d = st
            dx = sum(d[0:10:2])
            dy = sum(d[1:10:2])
            self.curveto(*d[0:6])
            if abs(dx) > abs(dy):
                self.curveto(d[6], d[7], d[8], d[9], d[10], -dy)
            else:
                self.curveto(d[6], d[7], d[8], d[9], -dx, d[10])
            st.clear()
        elif b2 == 3:
            b_, a = st.pop(), st.pop(); st.append(1 if a and b_ else 0)
        elif b2 == 4:
            b_, a = st.pop(), st.pop(); st.append(1 if a or b_ else 0)
        elif b2 == 5:
            st.append(0 if st.pop() else 1)
        elif b2 == 9:
            st.append(abs(st.pop()))
        elif b2 == 10:
            b_, a = st.pop(), st.pop(); st.append(a + b_)
        elif b2 == 11:
            b_, a = st.pop(), st.pop(); st.append(a - b_)
        elif b2 == 12:
            b_, a = st.pop(), st.pop(); st.append(a / b_ if b_ else 0)
        elif b2 == 14:
            st.append(-st.pop())
        elif b2 == 15:
            b_, a = st.pop(), st.pop(); st.append(1 if a == b_ else 0)
        elif b2 == 18:
            st.pop()
        elif b2 == 20:
            idx, v = int(st.pop()), st.pop(); self.trans[idx % 32] = v
        elif b2 == 21:
            st.append(self.trans[int(st.pop()) % 32])
        elif b2 == 22:
            v2, v1, s2, s1 = st.pop(), st.pop(), st.pop(), st.pop(); st.append(s1 if v1 <= v2 else s2)
        elif b2 == 23:
            st.append(0.5)
        elif b2 == 24:
            b_, a = st.pop(), st.pop(); st.append(a * b_)
        elif b2 == 26:
            import math
            st.append(math.sqrt(max(st.pop(), 0)))
        elif b2 == 27:
            st.append(st[-1])
        elif b2 == 28:
            st[-1], st[-2] = st[-2], st[-1]
        elif b2 == 29:
            i_ = int(st.pop()); st.append(st[-1 - max(i_, 0)])
        elif b2 == 30:
            j, n = int(st.pop()), int(st.pop())
            if n > 0:
                part = st[-n:]
                j %= n
                st[-n:] = part[-j:] + part[:-j] if j else part
        else:
            st.clear()
