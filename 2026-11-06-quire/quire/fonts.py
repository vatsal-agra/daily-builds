"""PDF font handling: encodings, ToUnicode, CID fonts, widths, and the bridge to the
font-program parsers (TrueType / CFF). A Font turns string bytes into Glyph records."""
import glob
import os
import re
from collections import namedtuple

from .lexer import Lexer, Punct
from .objects import Name, PdfString, Stream, Keyword
from .truetype import TrueTypeFont, FontError
from .cff import CFFFont
from .glyphlist import BASE_ENCODINGS, name_to_unicode, unicode_to_name, WIN_ANSI, STANDARD

# text: unicode for extraction; width: advance as fraction of the em; gid: glyph in program (or None)
Glyph = namedtuple("Glyph", "code text width gid nbytes is_space")

_SUBST_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
               "/Library/Fonts", "C:\\Windows\\Fonts"]
_subst_cache = {}


def _find_substitute(name, flags):
    low = (name or "").lower()
    bold = "bold" in low or "black" in low or "heavy" in low or bool(flags & (1 << 18))
    ital = "italic" in low or "oblique" in low or bool(flags & 64)
    mono = "courier" in low or "mono" in low or "consol" in low or bool(flags & 1)
    serif = ("times" in low or "serif" in low or "georgia" in low or "garamond" in low or "roman" in low
             or "palatino" in low or "book" in low or (bool(flags & 2) and "sans" not in low and "helvet" not in low and "arial" not in low))
    fam = "DejaVuSansMono" if mono else "DejaVuSerif" if serif else "DejaVuSans"
    style = ("-BoldOblique" if ital else "-Bold") if bold else ("-Oblique" if ital else "")
    if mono and ital:
        style = style
    if fam == "DejaVuSerif":
        style = style.replace("Oblique", "Italic")
    fn = fam + style + ".ttf"
    if fn in _subst_cache:
        return _subst_cache[fn]
    res = None
    for d in _SUBST_DIRS:
        p = os.path.join(d, fn)
        if os.path.exists(p):
            try:
                res = TrueTypeFont(open(p, "rb").read())
            except (OSError, FontError):
                res = None
            break
    _subst_cache[fn] = res
    return res


# ---------------------------------------------------------------- CMaps ----
class CMap:
    """Parsed CMap (ToUnicode or CID encoding)."""

    def __init__(self):
        self.codespaces = []   # (nbytes, lo, hi)
        self.bf = {}           # code -> unicode str   (ToUnicode)
        self.bf_ranges = []    # (lo, hi, base_unicode_str)  lazily applied
        self.cid_chars = {}    # code -> cid
        self.cid_ranges = []   # (lo, hi, cid0)
        self.identity = False
        self.vertical = False

    def to_unicode(self, code):
        if code in self.bf:
            return self.bf[code]
        for lo, hi, base in self.bf_ranges:
            if lo <= code <= hi:
                if not base:
                    return ""
                return base[:-1] + chr(ord(base[-1]) + code - lo)
        return None

    def to_cid(self, code):
        if self.identity:
            return code
        if code in self.cid_chars:
            return self.cid_chars[code]
        for lo, hi, c0 in self.cid_ranges:
            if lo <= code <= hi:
                return c0 + code - lo
        return 0

    def split(self, data):
        """Yield (code, nbytes) per the codespace ranges (default: 2 bytes)."""
        spaces = [c for c in self.codespaces if 1 <= c[0] <= 4] or [(2, 0, 0xFFFF)]
        maxn = max(s[0] for s in spaces)
        i, n = 0, len(data)
        while i < n:
            matched = False
            for ln in range(1, min(maxn, n - i) + 1):
                code = int.from_bytes(data[i:i + ln], "big")
                if any(s[0] == ln and _in_cs(code, s, ln) for s in spaces):
                    yield code, ln
                    i += ln
                    matched = True
                    break
            if not matched:  # byte(s) outside every codespace range (or a truncated tail): consume, never stall
                ln = max(1, min(spaces[0][0], n - i))
                yield int.from_bytes(data[i:i + ln], "big"), ln
                i += ln


def _in_cs(code, s, ln):
    # per-byte range check
    for k in range(ln):
        sh = 8 * (ln - 1 - k)
        b, lo, hi = (code >> sh) & 255, (s[1] >> sh) & 255, (s[2] >> sh) & 255
        if not lo <= b <= hi:
            return False
    return True


def _u16(s):
    s = bytes(s)
    try:
        return s.decode("utf-16-be")
    except UnicodeDecodeError:
        return s.decode("utf-16-be", "replace")


def parse_cmap(data):
    cm = CMap()
    lx = Lexer(data, 0)
    stack = []
    while True:
        try:
            t = lx.next_token()
        except Exception:  # noqa: BLE001
            break
        if t is None:
            break
        if isinstance(t, Keyword):
            if t == "endcodespacerange":
                for i in range(0, len(stack) - 1, 2):
                    if isinstance(stack[i], PdfString) and isinstance(stack[i + 1], PdfString):
                        cm.codespaces.append((len(stack[i]), int.from_bytes(stack[i], "big"), int.from_bytes(stack[i + 1], "big")))
                stack = []
            elif t == "endbfchar":
                for i in range(0, len(stack) - 1, 2):
                    if isinstance(stack[i], PdfString) and isinstance(stack[i + 1], PdfString):
                        cm.bf[int.from_bytes(stack[i], "big")] = _u16(stack[i + 1])
                stack = []
            elif t == "endbfrange":
                i = 0
                while i + 2 < len(stack):
                    lo, hi, dst = stack[i], stack[i + 1], stack[i + 2]
                    if isinstance(lo, PdfString) and isinstance(hi, PdfString):
                        a, b = int.from_bytes(lo, "big"), int.from_bytes(hi, "big")
                        if isinstance(dst, list):
                            for k, d in enumerate(dst):
                                if isinstance(d, PdfString) and a + k <= b:
                                    cm.bf[a + k] = _u16(d)
                        elif isinstance(dst, PdfString):
                            cm.bf_ranges.append((a, b, _u16(dst)))
                    i += 3
                stack = []
            elif t == "endcidchar":
                for i in range(0, len(stack) - 1, 2):
                    if isinstance(stack[i], PdfString) and isinstance(stack[i + 1], int):
                        cm.cid_chars[int.from_bytes(stack[i], "big")] = stack[i + 1]
                stack = []
            elif t == "endcidrange":
                for i in range(0, len(stack) - 2, 3):
                    if isinstance(stack[i], PdfString) and isinstance(stack[i + 1], PdfString) and isinstance(stack[i + 2], int):
                        cm.cid_ranges.append((int.from_bytes(stack[i], "big"), int.from_bytes(stack[i + 1], "big"), stack[i + 2]))
                stack = []
            elif t in ("begincodespacerange", "beginbfchar", "beginbfrange", "begincidchar", "begincidrange",
                       "beginnotdefrange", "beginnotdefchar"):
                stack = []
            elif t == "def":
                if len(stack) >= 2 and stack[-2] == "WMode" and stack[-1] == 1:
                    cm.vertical = True
                stack = []
            continue
        if isinstance(t, Punct) and t in ("[", "<<"):
            try:
                stack.append(lx.parse_object(t, allow_refs=False))
            except Exception:  # noqa: BLE001
                stack = []
            continue
        stack.append(t)
    return cm


# ------------------------------------------------------------ programs ----
class Program:
    """Uniform view over a font program: outlines in em units (1.0 = font size)."""

    def __init__(self, kind, obj):
        self.kind = kind          # 'tt' | 'cff'
        self.obj = obj            # TrueTypeFont or CFFFont
        if kind == "tt":
            self.scale = 1.0 / obj.units_per_em
            self.is_cff_sfnt = obj.is_cff
            self.cff = obj._cff
            if self.cff:
                m = self.cff.matrix
                self.scale = m[0] if m and m[0] else self.scale
        elif kind == "t1":
            self.scale = obj.matrix[0] or 0.001
            self.cff = None
            self.is_cff_sfnt = False
        else:
            self.scale = (obj.matrix[0] or 0.001)
            self.cff = obj
            self.is_cff_sfnt = False
        self._cache = {}

    def outline(self, gid):
        if gid in self._cache:
            return self._cache[gid]
        ops = self.obj.glyph(gid)
        s = self.scale
        out = []
        for op in ops:
            out.append((op[0],) + tuple(v * s for v in op[1:]))
        self._cache[gid] = out
        return out

    def advance(self, gid):
        if self.kind == "tt":
            a = self.obj.advance(gid)
            return a * self.scale if a is not None else None
        return None


def load_program(doc, desc):
    for key in ("FontFile2", "FontFile3", "FontFile"):
        ref = desc.get(key)
        s = doc.resolve(ref)
        if not isinstance(s, Stream):
            continue
        try:
            data = doc.decode_stream(s)
        except Exception:  # noqa: BLE001
            continue
        try:
            if key == "FontFile":
                return _t1_program(data)
            if data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf", b"typ1"):
                return Program("tt", TrueTypeFont(data))
            if data[:1] == b"\x01" and key == "FontFile3":
                return Program("cff", CFFFont(data))
            if data[:2] == b"%!" or data[:1] == b"\x80":
                return _t1_program(data)
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"font program unreadable ({key}): {type(e).__name__}: {e}")
    return None


def _t1_program(data):
    from .type1 import Type1Font
    return Program("t1", Type1Font(data))


# --------------------------------------------------------------- fonts ----
class Font:
    def __init__(self, doc, fd):
        self.doc = doc
        self.dict = fd
        r = doc.resolve
        self.subtype = str(r(fd.get("Subtype")) or "Type1")
        self.basefont = str(r(fd.get("BaseFont")) or "")
        self.name = re.sub(r"^[A-Z]{6}\+", "", self.basefont)
        self.composite = self.subtype == "Type0"
        self.tounicode = None
        tu = r(fd.get("ToUnicode"))
        if isinstance(tu, Stream):
            try:
                self.tounicode = parse_cmap(doc.decode_stream(tu))
            except Exception:  # noqa: BLE001
                self.tounicode = None
        self.program = None
        self.substituted = False
        self.vertical = False
        self.type3 = self.subtype == "Type3"
        self._glyphs = {}
        if self.type3:
            self._init_type3()
        elif self.composite:
            self._init_composite()
        else:
            self._init_simple()

    # ---------------------------------------------------------- simple fonts
    def _init_simple(self):
        r = self.doc.resolve
        fd = self.dict
        desc = r(fd.get("FontDescriptor")) or {}
        desc = {k: v for k, v in desc.items()} if isinstance(desc, dict) else {}
        self.flags = int(r(desc.get("Flags")) or 0)
        self.program = load_program(self.doc, desc)
        self._embedded = self.program is not None
        from .stdmetrics import std_widths
        self._std = std_widths(self.name)
        if self.program is None:
            sub = _find_substitute(self.name, self.flags)
            if sub is not None:
                self.program = Program("tt", sub)
                self.substituted = True
        self.first = int(r(fd.get("FirstChar")) or 0)
        w = r(fd.get("Widths"))
        self.widths = [r(x) for x in w] if isinstance(w, list) else None
        self.missing = r(desc.get("MissingWidth")) or 0
        # encoding
        enc = r(fd.get("Encoding"))
        base = None
        diffs = {}
        if isinstance(enc, (str, Name)):
            base = BASE_ENCODINGS.get(str(enc))
        elif isinstance(enc, dict):
            be = r(enc.get("BaseEncoding"))
            base = BASE_ENCODINGS.get(str(be)) if be else None
            d = r(enc.get("Differences")) or []
            code = 0
            for it in d:
                it = r(it)
                if isinstance(it, (int, float)):
                    code = int(it)
                elif isinstance(it, str):
                    diffs[code] = str(it)
                    code += 1
        self.has_encoding = bool(base) or bool(diffs) or enc is not None
        self.base_enc = base
        self.diffs = diffs
        symbolic = bool(self.flags & 4) and not (self.flags & 32)
        self.symbolic = symbolic
        self.std14 = self.name.split(",")[0].split("-")[0] in ("Symbol", "ZapfDingbats")
        if base is None and not symbolic and not self.std14:
            base = STANDARD if self.subtype.startswith("Type1") or self.subtype == "MMType1" else WIN_ANSI
            if self.program and self.program.kind == "cff" and self.program.obj.builtin_encoding:
                base = None
        self._base_used = base

    def _name_for(self, code):
        if code in self.diffs:
            return self.diffs[code]
        b = self._base_used
        if b and code in b:
            return unicode_to_name(b[code])
        return None

    def _gid_simple(self, code):
        p = self.program
        if p is None:
            return None
        name = self._name_for(code)
        if p.kind == "tt" and not p.is_cff_sfnt:
            tt = p.obj
            cm = tt.cmaps()
            if name is not None and (not self.symbolic or code in self.diffs or self.base_enc):
                u = name_to_unicode(name)
                if u and (3, 1) in cm:
                    g = cm[(3, 1)].get(ord(u[0]))
                    if g:
                        return g
                if (1, 0) in cm:
                    try:
                        mc = u.encode("mac_roman")[0] if u else None
                    except UnicodeEncodeError:
                        mc = None
                    if mc is not None and cm[(1, 0)].get(mc):
                        return cm[(1, 0)][mc]
                g = tt.glyph_names().get(name)
                if g:
                    return g
            for key in ((3, 0), (1, 0), (3, 1)):
                m = cm.get(key)
                if not m:
                    continue
                for c in (code, 0xF000 + code, 0xF100 + code, 0xF200 + code):
                    if c in m:
                        return m[c]
            if (3, 1) in cm and code in cm[(3, 1)]:
                return cm[(3, 1)][code]
            if not cm and code < tt.num_glyphs:
                return code
            return 0
        # CFF (bare or OpenType) / Type1-like programs with named glyphs
        cff = p.cff if p.kind in ("tt", "cff") else None
        if cff is not None:
            if name is not None and name in cff.name_to_gid:
                return cff.name_to_gid[name]
            if name is not None and not cff.is_cid:
                u = name_to_unicode(name)
                if u:
                    alt = unicode_to_name(u[0])
                    if alt in cff.name_to_gid:
                        return cff.name_to_gid[alt]
            if cff.builtin_encoding and code in cff.builtin_encoding and (name is None or not self.has_encoding):
                return cff.builtin_encoding[code]
            if cff.is_cid:
                return cff.cid_to_gid.get(code, 0)
            if p.kind == "tt" and p.obj.cmaps():
                for key in ((3, 1), (3, 0), (1, 0)):
                    if code in p.obj.cmaps().get(key, {}):
                        return p.obj.cmaps()[key][code]
            return 0
        if p.kind == "t1":
            t1 = p.obj
            if name is not None and name in t1.charstrings:
                return name
            if code in t1.encoding and name is None:
                return t1.encoding[code]
            if name is None:
                return None
            u = name_to_unicode(name)
            alt = unicode_to_name(u[0]) if u else None
            return alt if alt in t1.charstrings else None
        return None

    def _text_simple(self, code):
        if self.tounicode is not None:
            u = self.tounicode.to_unicode(code)
            if u is not None:
                return u
        name = self._name_for(code)
        if name:
            u = name_to_unicode(name)
            if u:
                return u
        if self.program and self.program.kind == "t1" and code in self.program.obj.encoding:
            u = name_to_unicode(self.program.obj.encoding[code])
            if u:
                return u
        if self.program and self.program.kind in ("tt", "cff") and self.program.cff and self.program.cff.builtin_encoding:
            cff = self.program.cff
            gid = cff.builtin_encoding.get(code)
            if gid is not None and gid < len(cff.glyph_names):
                u = name_to_unicode(cff.glyph_names[gid])
                if u:
                    return u
        if self.symbolic or self.std14:
            return ""
        return chr(code) if 32 <= code < 127 else ""

    def _width_simple(self, code, gid):
        i = code - self.first
        if self.widths is not None and 0 <= i < len(self.widths) and isinstance(self.widths[i], (int, float)):
            return self.widths[i] / 1000.0
        if self.widths is not None and self.missing:
            return self.missing / 1000.0
        if self.widths is None and not self._embedded and self._std is not None:
            ch = self._text_simple(code)
            if len(ch) == 1 and ch in self._std:
                return self._std[ch] / 1000.0
        if self.program and self.program.kind == "tt" and isinstance(gid, int):
            a = self.program.advance(gid)
            if a is not None:
                return a
        if self.program and self.program.kind == "t1" and gid is not None:
            return self.program.obj.advance(gid) * self.program.scale
        return (self.missing or 500) / 1000.0

    # ------------------------------------------------------- composite fonts
    def _init_composite(self):
        r = self.doc.resolve
        fd = self.dict
        df = r(r(fd.get("DescendantFonts"))[0])
        self.desc_dict = df
        desc = r(df.get("FontDescriptor")) or {}
        self.flags = int(r(desc.get("Flags")) or 0) if isinstance(desc, dict) else 0
        self.program = load_program(self.doc, desc) if isinstance(desc, dict) else None
        self.cid_subtype = str(r(df.get("Subtype")))
        enc = r(fd.get("Encoding"))
        self.cmap = CMap()
        if isinstance(enc, Stream):
            try:
                self.cmap = parse_cmap(self.doc.decode_stream(enc))
            except Exception:  # noqa: BLE001
                pass
            if not self.cmap.codespaces:
                self.cmap.codespaces = [(2, 0, 0xFFFF)]
            self.vertical = self.cmap.vertical
        else:
            nm = str(enc or "Identity-H")
            self.cmap.identity = True
            self.cmap.codespaces = [(2, 0, 0xFFFF)]
            self.vertical = nm.endswith("-V")
            if not nm.startswith("Identity"):
                self.doc.warnings.append(f"predefined CMap {nm} not available; treating as 2-byte identity")
        self.dw = r(df.get("DW"))
        self.dw = 1000 if self.dw is None else self.dw
        self.cid_w = {}
        w = r(df.get("W")) or []
        i = 0
        w = [r(x) for x in w]
        while i < len(w):
            c = w[i]
            if i + 1 < len(w) and isinstance(w[i + 1], list):
                for k, x in enumerate(w[i + 1]):
                    x = r(x)
                    if isinstance(x, (int, float)):
                        self.cid_w[c + k] = x
                i += 2
            elif i + 2 < len(w) and isinstance(c, int):
                c2, x = w[i + 1], w[i + 2]
                if isinstance(c2, int) and isinstance(x, (int, float)) and c2 - c < 70000:
                    for k in range(c, c2 + 1):
                        self.cid_w[k] = x
                i += 3
            else:
                break
        c2g = r(df.get("CIDToGIDMap"))
        self.cid2gid = None
        if isinstance(c2g, Stream):
            try:
                self.cid2gid = self.doc.decode_stream(c2g)
            except Exception:  # noqa: BLE001
                self.cid2gid = None

    def _reverse_cmap(self, gid):
        """No ToUnicode: recover text from the embedded font's own (3,1)/(3,10) cmap, glyph -> char."""
        p = self.program
        if gid is None or p is None or p.kind != "tt":
            return ""
        rev = getattr(p, "_rev", None)
        if rev is None:
            rev = {}
            cm = p.obj.cmaps()
            for key in ((3, 10), (3, 1), (0, 3), (0, 4)):
                for ch, g in cm.get(key, {}).items():
                    rev.setdefault(g, chr(ch))
            p._rev = rev
        return rev.get(gid, "")

    def _gid_cid(self, cid):
        p = self.program
        if p is None:
            return None
        if p.kind == "tt" and not p.is_cff_sfnt:
            if self.cid2gid is not None:
                return int.from_bytes(self.cid2gid[2 * cid:2 * cid + 2], "big") if 2 * cid + 2 <= len(self.cid2gid) else 0
            return cid
        cff = p.cff
        if cff is not None:
            if cff.is_cid:
                return cff.cid_to_gid.get(cid, 0)
            return cid
        return None

    # --------------------------------------------------------------- type 3
    def _init_type3(self):
        r = self.doc.resolve
        fd = self.dict
        self.matrix = [r(x) for x in (r(fd.get("FontMatrix")) or [0.001, 0, 0, 0.001, 0, 0])]
        self.charprocs = r(fd.get("CharProcs")) or {}
        self.t3_resources = r(fd.get("Resources"))
        self.first = int(r(fd.get("FirstChar")) or 0)
        w = r(fd.get("Widths"))
        self.widths = [r(x) for x in w] if isinstance(w, list) else []
        enc = r(fd.get("Encoding"))
        self.diffs = {}
        if isinstance(enc, dict):
            code = 0
            for it in r(enc.get("Differences")) or []:
                it = r(it)
                if isinstance(it, (int, float)):
                    code = int(it)
                elif isinstance(it, str):
                    self.diffs[code] = str(it)
                    code += 1
        self.flags = 0

    # ---------------------------------------------------------- public API
    def decode(self, data):
        """bytes -> [Glyph]"""
        out = []
        if self.composite:
            for code, ln in self.cmap.split(data):
                key = (code, ln)
                g = self._glyphs.get(key)
                if g is None:
                    cid = self.cmap.to_cid(code)
                    gid = self._gid_cid(cid)
                    text = self.tounicode.to_unicode(code) if self.tounicode else None
                    if text is None:
                        text = self._reverse_cmap(gid)
                    wd = self.cid_w.get(cid, self.dw) / 1000.0
                    g = Glyph(code, text, wd, gid, ln, ln == 1 and code == 32)
                    self._glyphs[key] = g
                out.append(g)
            return out
        for code in data:
            g = self._glyphs.get(code)
            if g is None:
                if self.type3:
                    i = code - self.first
                    wd = self.widths[i] if 0 <= i < len(self.widths) and isinstance(self.widths[i], (int, float)) else 0
                    nm = self.diffs.get(code)
                    text = name_to_unicode(nm) if nm else ""
                    if self.tounicode is not None:
                        t = self.tounicode.to_unicode(code)
                        text = t if t is not None else text
                    g = Glyph(code, text, wd * self.matrix[0], nm, 1, code == 32)
                else:
                    gid = self._gid_simple(code)
                    g = Glyph(code, self._text_simple(code), self._width_simple(code, gid), gid, 1, code == 32)
                self._glyphs[code] = g
            out.append(g)
        return out

    def outline(self, glyph):
        """Path ops in em units for this glyph, or None."""
        if self.program is None or glyph.gid is None:
            return None
        try:
            if self.program.kind == "t1":
                return self.program.obj.outline(glyph.gid, self.program.scale)
            return self.program.outline(glyph.gid)
        except Exception as e:  # noqa: BLE001 — corrupt glyph data: skip the glyph
            key = f"glyph {glyph.gid} of {self.name} unreadable"
            if key not in self.doc.warnings:
                self.doc.warnings.append(key)
            return None
