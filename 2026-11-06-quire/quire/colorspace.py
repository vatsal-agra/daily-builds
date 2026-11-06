"""Colour spaces -> RGB floats in [0,1]."""
from .objects import Name, Stream, PdfString
from .functions import Function, FunctionError


def clamp(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def cmyk_to_rgb(c, m, y, k):
    c, m, y, k = clamp(c), clamp(m), clamp(y), clamp(k)
    return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))


def _lab_to_rgb(L, a, b, wp=(0.9505, 1.0, 1.089)):
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200

    def g(t):
        return t ** 3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)
    X, Y, Z = wp[0] * g(fx), wp[1] * g(fy), wp[2] * g(fz)
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    gg = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bb = 0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def gam(u):
        u = clamp(u)
        return 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055
    return (gam(r), gam(gg), gam(bb))


class ColorSpace:
    def __init__(self, kind, n, **kw):
        self.kind = kind
        self.n = n
        self.__dict__.update(kw)

    def initial(self):
        if self.kind == "Indexed":
            return [0]
        if self.kind in ("Separation", "DeviceN"):
            return [1.0] * self.n
        if self.kind == "DeviceCMYK":
            return [0, 0, 0, 1]
        if self.kind == "Lab":
            return [0, 0, 0]
        return [0.0] * self.n

    def to_rgb(self, comps):
        k = self.kind
        try:
            if k in ("DeviceGray", "CalGray"):
                g = clamp(comps[0])
                return (g, g, g)
            if k in ("DeviceRGB", "CalRGB"):
                return (clamp(comps[0]), clamp(comps[1]), clamp(comps[2]))
            if k == "DeviceCMYK":
                return cmyk_to_rgb(*comps[:4])
            if k == "Lab":
                lo = self.range
                a = min(max(comps[1], lo[0]), lo[1])
                b = min(max(comps[2], lo[2]), lo[3])
                return _lab_to_rgb(min(max(comps[0], 0), 100), a, b, self.wp)
            if k == "Indexed":
                i = int(min(max(comps[0], 0), self.hival))
                nb = self.base.n
                raw = self.lookup[i * nb:(i + 1) * nb]
                if len(raw) < nb:
                    return (0.0, 0.0, 0.0)
                vals = [v / 255.0 for v in raw]
                if self.base.kind == "Lab":
                    r = self.base.range
                    vals = [vals[0] * 100, r[0] + vals[1] * (r[1] - r[0]), r[2] + vals[2] * (r[3] - r[2])]
                return self.base.to_rgb(vals)
            if k in ("Separation", "DeviceN"):
                if self.none:
                    return (1.0, 1.0, 1.0)
                alt = self.fn(*comps[:self.n])
                return self.alt.to_rgb(alt)
        except (IndexError, ZeroDivisionError, FunctionError):
            pass
        return (0.0, 0.0, 0.0)


GRAY = ColorSpace("DeviceGray", 1)
RGB = ColorSpace("DeviceRGB", 3)
CMYK = ColorSpace("DeviceCMYK", 4)
PATTERN = ColorSpace("Pattern", 0, under=None)


def parse_colorspace(doc, obj, resources=None, depth=0):
    r = doc.resolve
    obj = r(obj)
    if depth > 8:
        return GRAY
    if isinstance(obj, (str, Name)) and not isinstance(obj, list):
        nm = str(obj)
        if nm in ("DeviceGray", "G", "CalGray"):
            return GRAY
        if nm in ("DeviceRGB", "RGB", "CalRGB"):
            return RGB
        if nm in ("DeviceCMYK", "CMYK"):
            return CMYK
        if nm == "Pattern":
            return ColorSpace("Pattern", 0, under=None)
        if resources is not None:
            csd = r(resources.get("ColorSpace")) or {}
            if nm in csd:
                return parse_colorspace(doc, csd[nm], None, depth + 1)
        return GRAY
    if isinstance(obj, list) and obj:
        nm = str(r(obj[0]))
        if nm in ("DeviceGray", "G", "DeviceRGB", "RGB", "DeviceCMYK", "CMYK"):
            return parse_colorspace(doc, obj[0], resources, depth + 1)
        if nm == "CalGray":
            return ColorSpace("CalGray", 1)
        if nm == "CalRGB":
            return ColorSpace("CalRGB", 3)
        if nm == "Lab":
            d = r(obj[1]) or {}
            wp = [float(r(v)) for v in r(d.get("WhitePoint")) or [0.9505, 1, 1.089]]
            rg = [float(r(v)) for v in r(d.get("Range")) or [-100, 100, -100, 100]]
            return ColorSpace("Lab", 3, wp=wp, range=rg)
        if nm == "ICCBased":
            s = r(obj[1])
            d = s.dict if isinstance(s, Stream) else {}
            n = int(r(d.get("N")) or 3)
            alt = d.get("Alternate")
            if alt is not None:
                a = parse_colorspace(doc, alt, resources, depth + 1)
                if a.n == n and a.kind not in ("Indexed", "Pattern"):
                    return a
            return {1: GRAY, 3: RGB, 4: CMYK}.get(n, RGB)
        if nm in ("Indexed", "I"):
            base = parse_colorspace(doc, obj[1], resources, depth + 1)
            hival = int(r(obj[2]))
            lk = r(obj[3])
            if isinstance(lk, Stream):
                lk = doc.decode_stream(lk)
            return ColorSpace("Indexed", 1, base=base, hival=hival, lookup=bytes(lk or b""))
        if nm in ("Separation", "DeviceN"):
            names = r(obj[1])
            n = 1 if nm == "Separation" else len(names)
            alt = parse_colorspace(doc, obj[2], resources, depth + 1)
            fn = Function(doc, obj[3])
            none = (nm == "Separation" and str(names) == "None") or (nm == "DeviceN" and all(str(x) == "None" for x in names))
            return ColorSpace(nm, n, alt=alt, fn=fn, none=none)
        if nm == "Pattern":
            under = parse_colorspace(doc, obj[1], resources, depth + 1) if len(obj) > 1 else None
            return ColorSpace("Pattern", 0, under=under)
    return GRAY
