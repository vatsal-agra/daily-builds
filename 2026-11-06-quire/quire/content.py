"""Content-stream interpreter. Walks page/form/pattern/Type3 content and reports what
it finds to a Device (renderer, text extractor, ...)."""
import math
import re
from .lexer import Lexer, Punct, SyntaxErr
from .objects import Name, Ref, PdfString, Stream, Keyword
from . import colorspace as cs
from .fonts import Font
from .functions import Function, FunctionError

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mmul(a, b):
    """Apply a first, then b (PDF row-vector convention)."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def minv(m):
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-12:
        return None
    a, b, c, d = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return (a, b, c, d, -(m[4] * a + m[5] * c), -(m[4] * b + m[5] * d))


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def transform_path(ops, m):
    out = []
    for op in ops:
        if op[0] == "Z":
            out.append(op)
            continue
        pts = []
        for i in range(1, len(op), 2):
            x, y = apply(m, op[i], op[i + 1])
            pts += [x, y]
        out.append((op[0], *pts))
    return out


class Device:
    """Observer interface. All hooks are optional."""
    def save(self): pass
    def restore(self): pass
    def fill(self, path, m, evenodd, paint, alpha): pass
    def stroke(self, path, m, style, paint, alpha): pass
    def clip(self, path, m, evenodd): pass
    def image(self, doc, stream, m, alpha, fill_rgb): pass
    def shade(self, shading, m, alpha): pass
    def text(self, font, glyph, trm, advance_user, size, visible): pass
    def begin_text_object(self): pass
    def marked(self, tag, props): pass


class GState:
    def __init__(self):
        self.ctm = IDENT
        self.fill_cs = cs.GRAY
        self.stroke_cs = cs.GRAY
        self.fill_comps = [0.0]
        self.stroke_comps = [0.0]
        self.fill_paint = ("rgb", (0.0, 0.0, 0.0))
        self.stroke_paint = ("rgb", (0.0, 0.0, 0.0))
        self.lw = 1.0
        self.cap = 0
        self.join = 0
        self.miter = 10.0
        self.dash = ([], 0.0)
        self.fa = 1.0
        self.sa = 1.0
        self.font = None
        self.fsize = 0.0
        self.tc = 0.0
        self.tw = 0.0
        self.th = 1.0
        self.tl = 0.0
        self.tmode = 0
        self.trise = 0.0

    def copy(self):
        g = GState.__new__(GState)
        g.__dict__.update(self.__dict__)
        return g


class Shading:
    def __init__(self, doc, obj, resources):
        r = doc.resolve
        obj = r(obj)
        d = obj.dict if isinstance(obj, Stream) else obj
        self.doc = doc
        self.type = int(r(d.get("ShadingType")))
        self.cs = cs.parse_colorspace(doc, d.get("ColorSpace"), resources)
        self.coords = [float(r(v)) for v in r(d.get("Coords")) or []]
        self.domain = [float(r(v)) for v in r(d.get("Domain")) or [0, 1]]
        ext = r(d.get("Extend")) or [False, False]
        self.extend = [bool(r(ext[0])), bool(r(ext[1]))]
        fn = r(d.get("Function"))
        self.fns = []
        if fn is not None:
            lst = fn if isinstance(fn, list) else [fn]
            self.fns = [Function(doc, f) for f in lst]
        bg = r(d.get("Background"))
        self.background = self.cs.to_rgb([float(r(v)) for v in bg]) if bg else None
        bb = r(d.get("BBox"))
        self.bbox = [float(r(v)) for v in bb] if bb else None
        self.matrix = [float(r(v)) for v in r(d.get("Matrix")) or [1, 0, 0, 1, 0, 0]]
        self._lut = None

    def color_at(self, t):
        """t in the shading domain -> rgb"""
        if len(self.fns) == 1:
            comps = self.fns[0](t)
        elif self.fns:
            comps = [f(t)[0] for f in self.fns]
        else:
            comps = [t]
        return self.cs.to_rgb(comps)

    def lut(self, n=256):
        if self._lut is None:
            t0, t1 = self.domain[0], self.domain[1]
            self._lut = [self.color_at(t0 + (t1 - t0) * i / (n - 1)) for i in range(n)]
        return self._lut


class Interpreter:
    MAX_DEPTH = 14

    def __init__(self, doc, device, resources, base_ctm=IDENT, depth=0, hidden_ocgs=None, gs=None):
        self.doc = doc
        self.dev = device
        self.res = resources if isinstance(resources, dict) else {}
        self.base = base_ctm
        self.depth = depth
        self.gs = gs.copy() if gs is not None else GState()
        if gs is None:
            self.gs.ctm = base_ctm
        self.stack = []
        self.path = []
        self.cur = None
        self.pending_clip = None
        self.tm = IDENT
        self.tlm = IDENT
        self.text_clip = []
        self.font_cache = {}
        self.hidden = hidden_ocgs or set()
        self.oc_stack = []
        self.color_locked = False
        self.warnings = doc.warnings
        self._form_stack = []

    # --------------------------------------------------------------- helpers
    def _res(self, kind, name):
        d = self.doc.resolve(self.res.get(kind))
        if isinstance(d, dict):
            return d.get(name)
        return None

    def _is_hidden(self):
        return any(self.oc_stack)

    def _oc_hidden(self, oc):
        ref = oc
        d = self.doc.resolve(oc)
        if isinstance(ref, Ref) and ref.num in self.hidden:
            return True
        if isinstance(d, dict) and d.get("Type") == "OCMD":
            ocgs = d.get("OCGs")
            lst = ocgs if isinstance(ocgs, list) else [ocgs]
            states = [(isinstance(g, Ref) and g.num in self.hidden) for g in lst if g is not None]
            if not states:
                return False
            pol = str(self.doc.resolve(d.get("P")) or "AnyOn")
            on = [not s for s in states]
            return not {"AnyOn": any(on), "AllOn": all(on), "AnyOff": not all(on), "AllOff": not any(on)}.get(pol, any(on))
        return False

    # ------------------------------------------------------------------ run
    def run(self, data):
        lx = Lexer(data, 0)
        ops = []
        table = self._table()
        while True:
            try:
                t = lx.next_token()
            except Exception:  # noqa: BLE001
                break
            if t is None:
                break
            if isinstance(t, Keyword):
                if t == "true":
                    ops.append(True)
                elif t == "false":
                    ops.append(False)
                elif t == "null":
                    ops.append(None)
                elif t == "BI":
                    try:
                        self._inline_image(lx)
                    except Exception as e:  # noqa: BLE001
                        self.warnings.append(f"inline image skipped: {e}")
                    ops = []
                else:
                    fn = table.get(str(t))
                    if fn is not None:
                        try:
                            fn(ops)
                        except Exception as e:  # noqa: BLE001 — a bad operator must never abort the page
                            self.warnings.append(f"operator {t} failed: {type(e).__name__}: {e}")
                    ops = []
                continue
            if isinstance(t, Punct):
                if t in ("[", "<<"):
                    try:
                        ops.append(lx.parse_object(t, allow_refs=False))
                    except SyntaxErr:
                        break
                continue
            ops.append(t)
            if len(ops) > 512:
                ops = ops[-64:]

    def _table(self):
        return {
            "q": self.op_q, "Q": self.op_Q, "cm": self.op_cm, "w": self.op_w, "J": self.op_J, "j": self.op_j,
            "M": self.op_M, "d": self.op_d, "gs": self.op_gs, "ri": lambda o: None, "i": lambda o: None,
            "m": self.op_m, "l": self.op_l, "c": self.op_c, "v": self.op_v, "y": self.op_y, "h": self.op_h,
            "re": self.op_re, "S": lambda o: self.paint(False, False, True), "s": lambda o: (self.op_h(o), self.paint(False, False, True)),
            "f": lambda o: self.paint(True, False, False), "F": lambda o: self.paint(True, False, False),
            "f*": lambda o: self.paint(True, True, False), "B": lambda o: self.paint(True, False, True),
            "B*": lambda o: self.paint(True, True, True),
            "b": lambda o: (self.op_h(o), self.paint(True, False, True)),
            "b*": lambda o: (self.op_h(o), self.paint(True, True, True)), "n": lambda o: self.paint(False, False, False),
            "W": lambda o: setattr(self, "pending_clip", False), "W*": lambda o: setattr(self, "pending_clip", True),
            "BT": self.op_BT, "ET": self.op_ET, "Tc": lambda o: setattr(self.gs, "tc", float(o[-1])),
            "Tw": lambda o: setattr(self.gs, "tw", float(o[-1])), "Tz": lambda o: setattr(self.gs, "th", float(o[-1]) / 100),
            "TL": lambda o: setattr(self.gs, "tl", float(o[-1])), "Tf": self.op_Tf,
            "Tr": lambda o: setattr(self.gs, "tmode", int(o[-1])), "Ts": lambda o: setattr(self.gs, "trise", float(o[-1])),
            "Td": self.op_Td, "TD": self.op_TD, "Tm": self.op_Tm, "T*": self.op_Tstar,
            "Tj": self.op_Tj, "TJ": self.op_TJ, "'": self.op_quote, '"': self.op_dquote,
            "d0": lambda o: None, "d1": self.op_d1,
            "CS": lambda o: self.set_cs(o[-1], True), "cs": lambda o: self.set_cs(o[-1], False),
            "SC": lambda o: self.set_color(o, True), "SCN": lambda o: self.set_color(o, True),
            "sc": lambda o: self.set_color(o, False), "scn": lambda o: self.set_color(o, False),
            "G": lambda o: self.set_dev(cs.GRAY, o, True), "g": lambda o: self.set_dev(cs.GRAY, o, False),
            "RG": lambda o: self.set_dev(cs.RGB, o, True), "rg": lambda o: self.set_dev(cs.RGB, o, False),
            "K": lambda o: self.set_dev(cs.CMYK, o, True), "k": lambda o: self.set_dev(cs.CMYK, o, False),
            "sh": self.op_sh, "Do": self.op_Do,
            "MP": lambda o: None, "DP": lambda o: None, "BMC": self.op_BMC, "BDC": self.op_BDC, "EMC": self.op_EMC,
            "BX": lambda o: None, "EX": lambda o: None,
        }

    # ------------------------------------------------------- graphics state
    def op_q(self, o):
        self.stack.append(self.gs.copy())
        self.dev.save()

    def op_Q(self, o):
        if self.stack:
            self.gs = self.stack.pop()
            self.dev.restore()

    def op_cm(self, o):
        m = tuple(float(v) for v in o[-6:])
        self.gs.ctm = mmul(m, self.gs.ctm)

    def op_w(self, o): self.gs.lw = float(o[-1])
    def op_J(self, o): self.gs.cap = int(o[-1])
    def op_j(self, o): self.gs.join = int(o[-1])
    def op_M(self, o): self.gs.miter = float(o[-1])

    def op_d(self, o):
        arr = [float(self.doc.resolve(x)) for x in o[-2]]
        self.gs.dash = (arr, float(o[-1]))

    def op_gs(self, o):
        d = self.doc.resolve(self._res("ExtGState", o[-1]))
        if not isinstance(d, dict):
            return
        r = self.doc.resolve
        g = self.gs
        if "LW" in d: g.lw = float(r(d["LW"]))
        if "LC" in d: g.cap = int(r(d["LC"]))
        if "LJ" in d: g.join = int(r(d["LJ"]))
        if "ML" in d: g.miter = float(r(d["ML"]))
        if "D" in d:
            dd = r(d["D"])
            g.dash = ([float(r(x)) for x in r(dd[0])], float(r(dd[1])))
        sm = r(d.get("SMask"))
        if isinstance(sm, dict):
            self.warnings.append("soft mask (ExtGState /SMask) not supported: drawn unmasked") if "soft mask" not in " ".join(self.warnings) else None
        bm = r(d.get("BM"))
        if isinstance(bm, list) and bm:
            bm = r(bm[0])
        if bm is not None and str(bm) not in ("Normal", "Compatible"):
            msg = f"blend mode {bm} not supported: drawn as Normal"
            if msg not in self.warnings:
                self.warnings.append(msg)
        if "CA" in d: g.sa = float(r(d["CA"]))
        if "ca" in d: g.fa = float(r(d["ca"]))
        if "Font" in d:
            f = r(d["Font"])
            if isinstance(f, list) and len(f) == 2:
                g.font = self._font_from_ref(f[0])
                g.fsize = float(r(f[1]))

    # ------------------------------------------------------------- paths
    def op_m(self, o):
        x, y = float(o[-2]), float(o[-1])
        self.path.append(("M", x, y))
        self.cur = (x, y)

    def op_l(self, o):
        x, y = float(o[-2]), float(o[-1])
        if self.cur is None:
            self.path.append(("M", x, y))
        else:
            self.path.append(("L", x, y))
        self.cur = (x, y)

    def op_c(self, o):
        v = [float(x) for x in o[-6:]]
        if self.cur is None:
            self.path.append(("M", v[0], v[1]))
        self.path.append(("C", *v))
        self.cur = (v[4], v[5])

    def op_v(self, o):
        v = [float(x) for x in o[-4:]]
        if self.cur is None:
            self.cur = (v[0], v[1])
            self.path.append(("M", v[0], v[1]))
        self.path.append(("C", self.cur[0], self.cur[1], *v))
        self.cur = (v[2], v[3])

    def op_y(self, o):
        v = [float(x) for x in o[-4:]]
        if self.cur is None:
            self.path.append(("M", v[0], v[1]))
        self.path.append(("C", v[0], v[1], v[2], v[3], v[2], v[3]))
        self.cur = (v[2], v[3])

    def op_h(self, o):
        if self.path and self.path[-1][0] != "Z":
            self.path.append(("Z",))
            # current point returns to subpath start
            for op in reversed(self.path):
                if op[0] == "M":
                    self.cur = (op[1], op[2])
                    break

    def op_re(self, o):
        x, y, w, h = (float(v) for v in o[-4:])
        self.path += [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
        self.cur = (x, y)

    def paint(self, fill, evenodd, stroke):
        g = self.gs
        path = self.path
        hidden = self._is_hidden()
        if path and not hidden:
            if fill:
                self.dev.fill(path, g.ctm, evenodd, g.fill_paint, g.fa)
            if stroke:
                self.dev.stroke(path, g.ctm, self._style(), g.stroke_paint, g.sa)
        if self.pending_clip is not None:
            self.dev.clip(path, g.ctm, self.pending_clip)
        self.pending_clip = None
        self.path = []
        self.cur = None

    def _style(self):
        g = self.gs
        return {"w": g.lw, "cap": g.cap, "join": g.join, "miter": g.miter, "dash": g.dash}

    # ------------------------------------------------------------ colours
    def set_cs(self, name, stroke):
        space = cs.parse_colorspace(self.doc, name, self.res)
        g = self.gs
        comps = space.initial()
        if stroke:
            g.stroke_cs, g.stroke_comps = space, comps
        else:
            g.fill_cs, g.fill_comps = space, comps
        self._refresh(stroke, None)

    def set_dev(self, space, o, stroke):
        if self.color_locked:
            return
        n = space.n
        comps = [float(v) for v in o[-n:]]
        g = self.gs
        if stroke:
            g.stroke_cs, g.stroke_comps = space, comps
        else:
            g.fill_cs, g.fill_comps = space, comps
        self._refresh(stroke, None)

    def set_color(self, o, stroke):
        if self.color_locked:
            return
        g = self.gs
        space = g.stroke_cs if stroke else g.fill_cs
        if space.kind == "Pattern":
            name = o[-1] if o and isinstance(o[-1], str) else None
            comps = [float(v) for v in o[:-1] if isinstance(v, (int, float))]
            self._refresh(stroke, (name, comps))
            return
        comps = [float(v) for v in o if isinstance(v, (int, float))]
        if len(comps) < space.n:
            comps += [0.0] * (space.n - len(comps))
        comps = comps[-space.n:] if space.n else comps
        if stroke:
            g.stroke_comps = comps
        else:
            g.fill_comps = comps
        self._refresh(stroke, None)

    def _refresh(self, stroke, pattern):
        g = self.gs
        space = g.stroke_cs if stroke else g.fill_cs
        if space.kind == "Pattern":
            paint = ("rgb", (0.0, 0.0, 0.0))
            if pattern and pattern[0]:
                paint = self._pattern_paint(pattern[0], pattern[1], space) or paint
        else:
            paint = ("rgb", space.to_rgb(g.stroke_comps if stroke else g.fill_comps))
        if stroke:
            g.stroke_paint = paint
        else:
            g.fill_paint = paint

    def _pattern_paint(self, name, comps, space):
        pat = self.doc.resolve(self._res("Pattern", name))
        d = pat.dict if isinstance(pat, Stream) else pat
        if not isinstance(d, dict):
            return None
        r = self.doc.resolve
        pm = tuple(float(r(v)) for v in r(d.get("Matrix")) or IDENT)
        m = mmul(pm, self.base)
        pt = int(r(d.get("PatternType")))
        if pt == 2:
            try:
                sh = Shading(self.doc, d.get("Shading"), self.res)
            except Exception as e:  # noqa: BLE001
                self.warnings.append(f"shading pattern unusable: {e}")
                return None
            return ("shading", sh, m)
        if pt == 1 and isinstance(pat, Stream):
            rgb = None
            if int(r(d.get("PaintType")) or 1) == 2 and space.under is not None:
                rgb = space.under.to_rgb(comps)
            return ("tiling", pat, m, rgb)
        return None

    # --------------------------------------------------------------- text
    def op_BT(self, o):
        self.tm = self.tlm = IDENT
        self.text_clip = []
        self.dev.begin_text_object()

    def op_ET(self, o):
        if self.text_clip:
            self.dev.clip(self.text_clip, IDENT if False else self.gs.ctm, False)
        self.text_clip = []

    def _font_from_ref(self, ref):
        key = ref.num if isinstance(ref, Ref) else id(ref)
        f = self.font_cache.get(key)
        if f is None:
            fd = self.doc.resolve(ref)
            if not isinstance(fd, dict):
                return None
            f = self.doc.__dict__.setdefault("_font_objs", {}).get(key)
            if f is None:
                try:
                    f = Font(self.doc, fd)
                except Exception as e:  # noqa: BLE001
                    self.warnings.append(f"font unusable: {type(e).__name__}: {e}")
                    return None
                self.doc._font_objs[key] = f
            self.font_cache[key] = f
        return f

    def op_Tf(self, o):
        ref = self._res("Font", o[-2])
        self.gs.font = self._font_from_ref(ref) if ref is not None else None
        self.gs.fsize = float(o[-1])

    def op_Td(self, o):
        self.tlm = mmul((1, 0, 0, 1, float(o[-2]), float(o[-1])), self.tlm)
        self.tm = self.tlm

    def op_TD(self, o):
        self.gs.tl = -float(o[-1])
        self.op_Td(o)

    def op_Tm(self, o):
        self.tm = self.tlm = tuple(float(v) for v in o[-6:])

    def op_Tstar(self, o):
        self.op_Td([0, -self.gs.tl])

    def op_Tj(self, o):
        if isinstance(o[-1], PdfString):
            self._show(bytes(o[-1]))

    def op_TJ(self, o):
        for it in o[-1]:
            if isinstance(it, PdfString):
                self._show(bytes(it))
            elif isinstance(it, (int, float)):
                g = self.gs
                tx = -it / 1000.0 * g.fsize * g.th
                self.tm = mmul((1, 0, 0, 1, tx, 0), self.tm)

    def op_quote(self, o):
        self.op_Tstar(o)
        self.op_Tj(o)

    def op_dquote(self, o):
        self.gs.tw = float(o[-3])
        self.gs.tc = float(o[-2])
        self.op_Tstar(o)
        self.op_Tj(o)

    def op_d1(self, o):
        self.color_locked = True

    def _show(self, data):
        g = self.gs
        font = g.font
        if font is None:
            return
        glyphs = font.decode(data)
        fs, th = g.fsize, g.th
        visible = g.tmode != 3 and not self._is_hidden()
        for gl in glyphs:
            text_m = mmul((fs * th, 0, 0, fs, 0, g.trise), self.tm)
            trm = mmul(text_m, g.ctm)
            adv = gl.width * fs
            adv_user = gl.width * math.hypot(trm[0], trm[1])
            self.dev.text(font, gl, trm, adv_user, fs, visible)
            if visible or g.tmode >= 4:
                self._paint_glyph(font, gl, text_m, trm)
            tx = (adv + g.tc + (g.tw if gl.is_space else 0.0)) * th
            self.tm = mmul((1, 0, 0, 1, tx, 0), self.tm)

    def _paint_glyph(self, font, gl, text_m, trm):
        g = self.gs
        mode = g.tmode
        if font.type3:
            if mode in (0, 2, 4, 6) or mode == 1:
                self._type3_glyph(font, gl, text_m)
            return
        ops = font.outline(gl)
        if not ops:
            return
        if mode in (0, 2, 4, 6):
            self.dev.fill(ops, trm, False, g.fill_paint, g.fa)
        if mode in (1, 2, 5, 6):
            self.dev.stroke(transform_path(ops, text_m), g.ctm, self._style(), g.stroke_paint, g.sa)
        if mode >= 4:
            self.text_clip += transform_path(ops, text_m)

    def _type3_glyph(self, font, gl, text_m):
        if self.depth >= self.MAX_DEPTH or gl.gid is None:
            return
        proc = self.doc.resolve(font.charprocs.get(gl.gid))
        if not isinstance(proc, Stream):
            return
        try:
            data = self.doc.decode_stream(proc)
        except Exception:  # noqa: BLE001
            return
        m = mmul(tuple(font.matrix), mmul(text_m, self.gs.ctm))
        sub_gs = self.gs.copy()
        sub_gs.ctm = m
        res = font.t3_resources if isinstance(font.t3_resources, dict) else self.res
        it = Interpreter(self.doc, self.dev, res, self.base, self.depth + 1, self.hidden, sub_gs)
        it.font_cache = self.font_cache
        self.dev.save()
        it.run(data)
        self.dev.restore()

    # -------------------------------------------------------------- shading
    def op_sh(self, o):
        if self._is_hidden():
            return
        sh_obj = self._res("Shading", o[-1])
        try:
            sh = Shading(self.doc, sh_obj, self.res)
        except Exception as e:  # noqa: BLE001
            self.warnings.append(f"shading unusable: {e}")
            return
        self.dev.shade(sh, self.gs.ctm, self.gs.fa)

    # ----------------------------------------------------------- xobjects
    def op_Do(self, o):
        ref = self._res("XObject", o[-1])
        xo = self.doc.resolve(ref)
        if not isinstance(xo, Stream):
            return
        if self._is_hidden():
            return
        oc = xo.dict.get("OC")
        if oc is not None and self._oc_hidden(oc):
            return
        st = self.doc.resolve(xo.dict.get("Subtype"))
        if st == "Image":
            fill_rgb = self.gs.fill_paint[1] if self.gs.fill_paint[0] == "rgb" else (0.0, 0.0, 0.0)
            self.dev.image(self.doc, xo, self.gs.ctm, self.gs.fa, fill_rgb)
        elif st == "Form":
            self._form(xo, ref)

    def _form(self, xo, ref):
        if self.depth >= self.MAX_DEPTH:
            return
        key = ref.num if isinstance(ref, Ref) else id(xo)
        if key in self._form_stack:
            return
        r = self.doc.resolve
        m = tuple(float(r(v)) for v in r(xo.dict.get("Matrix")) or IDENT)
        try:
            data = self.doc.decode_stream(xo)
        except Exception as e:  # noqa: BLE001
            self.warnings.append(f"form XObject undecodable: {e}")
            return
        res = r(xo.dict.get("Resources"))
        res = res if isinstance(res, dict) else self.res
        sub_gs = self.gs.copy()
        sub_gs.ctm = mmul(m, self.gs.ctm)
        it = Interpreter(self.doc, self.dev, res, sub_gs.ctm, self.depth + 1, self.hidden, sub_gs)
        it.font_cache = self.font_cache
        it._form_stack = self._form_stack + [key]
        it.oc_stack = list(self.oc_stack)
        self.dev.save()
        bb = r(xo.dict.get("BBox"))
        if bb and len(bb) == 4:
            x0, y0, x1, y1 = (float(r(v)) for v in bb)
            self.dev.clip([("M", x0, y0), ("L", x1, y0), ("L", x1, y1), ("L", x0, y1), ("Z",)], sub_gs.ctm, False)
        it.run(data)
        self.dev.restore()

    # ------------------------------------------------------ marked content
    def op_BMC(self, o):
        self.oc_stack.append(False)

    def op_BDC(self, o):
        hide = False
        if len(o) >= 2 and o[-2] == "OC":
            prop = o[-1]
            if isinstance(prop, str):
                prop = self._res("Properties", prop)
            if prop is not None:
                hide = self._oc_hidden(prop)
        self.oc_stack.append(hide)

    def op_EMC(self, o):
        if self.oc_stack:
            self.oc_stack.pop()

    # --------------------------------------------------------- inline image
    def _inline_image(self, lx):
        d = {}
        while True:
            t = lx.next_token()
            if t is None:
                raise SyntaxErr("EOF in inline image")
            if isinstance(t, Keyword) and t == "ID":
                break
            if not isinstance(t, Name):
                continue
            d[str(t)] = lx.parse_object(allow_refs=False)
        data = lx.data
        p = lx.pos
        if data[p:p + 1] in (b" ", b"\n", b"\t", b"\r"):
            p += 1
            if data[p - 1:p] == b"\r" and data[p:p + 1] == b"\n":
                p += 1
        full = {"W": "Width", "H": "Height", "BPC": "BitsPerComponent", "CS": "ColorSpace", "F": "Filter",
                "DP": "DecodeParms", "IM": "ImageMask", "D": "Decode", "I": "Interpolate"}
        dd = {full.get(k, k): v for k, v in d.items()}
        cspace = dd.get("ColorSpace")
        if isinstance(cspace, str):
            cspace = Name({"G": "DeviceGray", "RGB": "DeviceRGB", "CMYK": "DeviceCMYK", "I": "Indexed"}.get(cspace, cspace))
        elif isinstance(cspace, list) and cspace and cspace[0] in ("I", "Indexed"):
            base = cspace[1]
            if isinstance(base, str):
                base = Name({"G": "DeviceGray", "RGB": "DeviceRGB", "CMYK": "DeviceCMYK"}.get(base, base))
            cspace = [Name("Indexed"), base] + cspace[2:]
        if cspace is not None:
            dd["ColorSpace"] = cspace
        filt = dd.get("Filter")
        if filt is None:
            w, h = int(dd["Width"]), int(dd["Height"])
            bpc = 1 if dd.get("ImageMask") else int(dd.get("BitsPerComponent", 8))
            n = 1
            if not dd.get("ImageMask"):
                n = cs.parse_colorspace(self.doc, dd.get("ColorSpace"), self.res).n or 1
            ln = ((w * n * bpc + 7) // 8) * h
            raw = data[p:p + ln]
            end = p + ln
        else:
            m = re.compile(rb"[\r\n\t ]EI(?=[\r\n\t ]|$)").search
            pos = p
            while True:
                mm = m(data, pos)
                if not mm:
                    raw = data[p:]
                    end = len(data)
                    break
                tail = data[mm.end():mm.end() + 20]
                if re.match(rb"^[\r\n\t ]*([A-Za-z*'\"0-9\.\-\[<]|$)", tail) and not re.search(rb"[\x00-\x08\x0e-\x1f\x80-\xff]", tail):
                    raw = data[p:mm.start()]
                    end = mm.start()
                    break
                pos = mm.end()
        lx.pos = end
        t = lx.next_token()
        while t is not None and not (isinstance(t, Keyword) and t == "EI"):
            t = lx.next_token()
        if self._is_hidden():
            return
        dd["Subtype"] = Name("Image")
        stm = Stream(dd, raw)
        fill_rgb = self.gs.fill_paint[1] if self.gs.fill_paint[0] == "rgb" else (0.0, 0.0, 0.0)
        stm._inline_res = self.res
        self.dev.image(self.doc, stm, self.gs.ctm, self.gs.fa, fill_rgb)


def hidden_ocgs(doc):
    """Set of OCG object numbers that are OFF in the default configuration."""
    out = set()
    try:
        ocp = doc.resolve(doc.catalog.get("OCProperties"))
        if not isinstance(ocp, dict):
            return out
        d = doc.resolve(ocp.get("D")) or {}
        if str(doc.resolve(d.get("BaseState")) or "ON") == "OFF":
            for g in doc.resolve(ocp.get("OCGs")) or []:
                if isinstance(g, Ref):
                    out.add(g.num)
            for g in doc.resolve(d.get("ON")) or []:
                if isinstance(g, Ref):
                    out.discard(g.num)
        for g in doc.resolve(d.get("OFF")) or []:
            if isinstance(g, Ref):
                out.add(g.num)
    except Exception:  # noqa: BLE001
        pass
    return out
