"""Hand-built PDFs, each exercising one rendering feature. Used by test_gallery.py and tools/gallery.py."""
import os, sys, zlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdfbuilder import PB, std_font
from quire.objects import Name, Ref, PdfString

CASES = {}


def case(fn):
    CASES[fn.__name__] = fn
    return fn


def one(content, res=None, box=(0, 0, 200, 200), extra=None, setup=None):
    b = PB()
    r = dict(res or {})
    if setup:
        r.update(setup(b))
    return b.page(content, r, box, extra)


@case
def strokes():
    return one("""
5 w 20 180 m 180 180 l S
1 J 10 w 20 160 m 100 160 l S
2 J 10 w 20 140 m 100 140 l S
0 J 0 j 12 w 20 100 m 50 130 l 80 100 l S
1 j 100 100 m 130 130 l 160 100 l S
2 j 20 60 m 50 90 l 80 60 l S
0 j 2 M 100 60 m 130 90 l 160 60 l S
[8 4] 0 d 3 w 20 40 m 180 40 l S
[2 6] 3 d 1 J 4 w 20 25 m 180 25 l S
[] 0 d 0 J 0 w 20 10 m 180 18 l S
0.5 w 1 0 0 RG 20 5 m 180 5 l S
""")


@case
def fills():
    return one("""
1 0 0 rg 20 20 80 80 re 40 40 40 40 re f
0 0 1 rg 110 20 80 80 re 130 40 40 40 re f*
0 0.6 0 rg 20 110 m 100 190 l 180 110 l 100 130 l h f
0.5 g 120 120 m 190 120 l 190 190 l h B
1 0.5 0 RG 3 w 0.2 0.4 0.9 rg 30 120 40 60 re B
""")


@case
def clipping():
    return one("""
q 30 30 100 100 re W n 1 0 0 rg 0 0 200 200 re f Q
q 100 100 m 190 100 l 145 190 l h W n 0 0 1 rg 0 0 200 200 re f
  1 1 0 rg 150 120 30 30 re f Q
q 20 150 m 60 190 l 100 150 l 60 160 l h W* n 0 0.7 0 rg 0 140 120 60 re f Q
q 20 20 60 60 re 40 40 60 60 re W* n 0.5 0 0.5 rg 0 0 200 200 re f Q
""")


@case
def colors():
    def setup(b):
        fn = b.add({"FunctionType": 2, "Domain": [0, 1], "C0": [0, 0, 0, 0], "C1": [0, 1, 1, 0], "N": 1})
        ps = b.add({"FunctionType": 4, "Domain": [0, 1], "Range": [0, 1, 0, 1, 0, 1]}, stream=b"{ dup 0.5 gt { 1 exch sub 2 mul 0 exch 1 } { 2 mul 1 exch 0 } ifelse }")
        return {"ColorSpace": {"Sep": [Name("Separation"), Name("Spot"), Name("DeviceCMYK"), fn],
                               "Sep2": [Name("Separation"), Name("Funky"), Name("DeviceRGB"), ps],
                               "Lab": [Name("Lab"), {"WhitePoint": [0.9505, 1, 1.089], "Range": [-100, 100, -100, 100]}],
                               "Cal": [Name("CalRGB"), {"WhitePoint": [0.95, 1, 1.09]}]}}
    return one("""
0.2 g 10 150 40 40 re f
0.2 0.4 0.8 rg 55 150 40 40 re f
0 1 1 0 k 100 150 40 40 re f
0.3 0.1 0.2 0.1 k 145 150 40 40 re f
/Sep cs 1 scn 10 100 40 40 re f 0.5 scn 55 100 40 40 re f
/Sep2 cs 0.2 scn 100 100 40 40 re f 0.9 scn 145 100 40 40 re f
/Lab cs 60 40 30 sc 10 50 40 40 re f 80 -50 50 sc 55 50 40 40 re f
/Cal cs 0.9 0.5 0.1 sc 100 50 40 40 re f
1 0 0 RG 4 w 145 50 40 40 re S
""", setup=setup)


def _raw_image(b, w, h, data, cs, bpc=8, extra=None, filt=True):
    d = {"Type": Name("XObject"), "Subtype": Name("Image"), "Width": w, "Height": h, "ColorSpace": cs, "BitsPerComponent": bpc}
    d.update(extra or {})
    return b.add(d, stream=data, compress=filt)


@case
def images():
    def setup(b):
        w, h = 16, 16
        rgb = bytes(v for y in range(h) for x in range(w) for v in (x * 16, y * 16, 128))
        im1 = _raw_image(b, w, h, rgb, Name("DeviceRGB"))
        gray1 = bytes(int(255 * ((x // 2 + y // 2) % 2)) for y in range(h) for x in range(w))
        # 1-bit checker
        bits = bytearray()
        for y in range(h):
            row = 0
            for x in range(w):
                row = (row << 1) | ((x // 4 + y // 4) % 2)
            bits += row.to_bytes(2, "big")
        im2 = _raw_image(b, w, h, bytes(bits), Name("DeviceGray"), 1)
        pal = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
        idx4 = bytearray()
        for y in range(h):
            for x in range(0, w, 2):
                idx4.append(((x // 4 + y // 4) % 4) << 4 | ((x // 4 + y // 4 + 1) % 4))
        im3 = _raw_image(b, w, h, bytes(idx4), [Name("Indexed"), Name("DeviceRGB"), 3, PdfString(pal)], 4)
        sm = _raw_image(b, w, h, bytes(min(255, x * 17) for y in range(h) for x in range(w)), Name("DeviceGray"))
        im4 = _raw_image(b, w, h, rgb, Name("DeviceRGB"), extra={"SMask": sm})
        stencil = b.add({"Type": Name("XObject"), "Subtype": Name("Image"), "Width": w, "Height": h, "ImageMask": True, "BitsPerComponent": 1}, stream=bytes(bits), compress=True)
        keyed = _raw_image(b, w, h, rgb, Name("DeviceRGB"), extra={"Mask": [0, 70, 0, 255, 0, 255]})
        big = _raw_image(b, 400, 300, bytes(v for y in range(300) for x in range(400) for v in ((x * 255 // 400), (y * 255 // 300), ((x + y) % 64) * 4)), Name("DeviceRGB"))
        return {"XObject": {"I1": im1, "I2": im2, "I3": im3, "I4": im4, "I5": stencil, "I6": keyed, "I7": big}}
    return one("""
0.9 0.9 0.6 rg 0 0 200 200 re f
q 40 0 0 40 10 150 cm /I1 Do Q
q 40 0 0 40 55 150 cm /I2 Do Q
q 40 0 0 40 100 150 cm /I3 Do Q
q 40 0 0 40 145 150 cm /I4 Do Q
1 0 0 rg q 40 0 0 40 10 100 cm /I5 Do Q
q 40 0 0 40 55 100 cm /I6 Do Q
q 40 0 0 40 100 100 cm /I7 Do Q
q 30 15 -15 30 160 100 cm /I1 Do Q
q 0.7 0.7 -0.7 0.7 60 30 cm 40 0 0 40 0 0 cm /I1 Do Q
q 20 0 0 20 130 30 cm
BI /W 4 /H 4 /BPC 8 /CS /G ID """.replace("ID ", "ID ") + "\x00\x40\x80\xff\x40\x80\xff\x00\x80\xff\x00\x40\xff\x00\x40\x80" + """
EI Q
""", setup=setup)


@case
def shadings():
    def setup(b):
        fn = b.add({"FunctionType": 2, "Domain": [0, 1], "C0": [1, 0, 0], "C1": [0, 0, 1], "N": 1})
        fn3 = b.add({"FunctionType": 3, "Domain": [0, 1], "Functions": [fn, b.add({"FunctionType": 2, "Domain": [0, 1], "C0": [0, 0, 1], "C1": [1, 1, 0], "N": 1})], "Bounds": [0.4], "Encode": [0, 1, 0, 1]})
        ax = b.add({"ShadingType": 2, "ColorSpace": Name("DeviceRGB"), "Coords": [20, 0, 100, 0], "Function": fn3, "Extend": [True, False]})
        rad = b.add({"ShadingType": 3, "ColorSpace": Name("DeviceRGB"), "Coords": [150, 150, 5, 150, 150, 40], "Function": fn, "Extend": [False, True]})
        pat = b.add({"Type": Name("Pattern"), "PatternType": 2, "Shading": {"ShadingType": 2, "ColorSpace": Name("DeviceRGB"), "Coords": [0, 0, 60, 60], "Function": fn}, "Matrix": [1, 0, 0, 1, 20, 20]})
        tile = b.add({"Type": Name("Pattern"), "PatternType": 1, "PaintType": 1, "TilingType": 1, "BBox": [0, 0, 20, 20], "XStep": 20, "YStep": 20, "Resources": {}, "Matrix": [1, 0, 0, 1, 0, 0]},
                     stream=b"1 0 0 rg 0 0 10 10 re f 0 0 1 rg 10 10 10 10 re f")
        tile2 = b.add({"Type": Name("Pattern"), "PatternType": 1, "PaintType": 2, "TilingType": 1, "BBox": [0, 0, 10, 10], "XStep": 12, "YStep": 12, "Resources": {}},
                      stream=b"5 5 m 10 5 l 5 10 l f 0 0 4 4 re f")
        return {"Shading": {"S1": ax, "S2": rad}, "Pattern": {"P1": pat, "P2": tile, "P3": tile2},
                "ColorSpace": {"PCS": [Name("Pattern"), Name("DeviceRGB")]}}
    return one("""
q 10 110 100 40 re W n /S1 sh Q
q 100 100 100 100 re W n /S2 sh Q
/Pattern cs /P1 scn 20 20 60 60 re f
/Pattern cs /P2 scn 100 20 80 60 re f
/PCS cs 0 0.6 0 /P3 scn 10 160 80 30 re f
""", setup=setup)


@case
def forms_and_alpha():
    def setup(b):
        inner = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 50, 50], "Matrix": [1, 0, 0, 1, 5, 5]},
                      stream=b"0 0 1 rg 0 0 100 100 re f 1 1 0 rg 10 10 20 20 re f")
        outer = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 100, 100], "Matrix": [0.5, 0, 0, 0.5, 0, 0],
                       "Resources": {"XObject": {"In": inner}}}, stream=b"1 0 0 rg 0 0 100 100 re f q 1 0 0 1 20 20 cm /In Do Q")
        return {"XObject": {"Fm": outer}, "ExtGState": {"A": {"ca": 0.5, "CA": 0.5}, "B": {"ca": 1, "LW": 8}}}
    return one("""
q 1 0 0 1 20 120 cm /Fm Do Q
q 2 0 0 2 100 100 cm /Fm Do Q
0 0.6 0 rg 20 20 100 60 re f
/A gs 1 0 0 rg 60 40 100 60 re f 0 0 1 RG 10 w 30 30 m 170 90 l S
/B gs 0 g 1 0 0 RG 150 20 m 190 20 l S
""", setup=setup)


@case
def rotated_90():
    return _rot(90)


@case
def rotated_180():
    return _rot(180)


@case
def rotated_270():
    return _rot(270)


def _rot(deg):
    return one("1 0 0 rg 10 10 50 20 re f 0 0 1 rg 140 170 50 20 re f 0 0.6 0 RG 3 w 10 100 m 190 100 l S", box=(0, 0, 200, 200), extra={"Rotate": deg}) if False else _rot_nonsquare(deg)


def _rot_nonsquare(deg):
    return one("1 0 0 rg 10 10 50 20 re f 0 0 1 rg 240 120 50 20 re f 0 0.6 0 RG 3 w 10 70 m 290 70 l S 0 g 20 100 m 60 130 l 20 130 l f",
               box=(0, 0, 300, 150), extra={"Rotate": deg})


@case
def cropbox_offset():
    return one("1 0 0 rg 100 100 50 50 re f 0 0 1 rg 130 130 80 80 re f", box=(50, 50, 250, 250), extra={"CropBox": [90, 90, 190, 170]})


@case
def optional_content():
    def setup(b):
        on = b.add({"Type": Name("OCG"), "Name": PdfString(b"on")})
        off = b.add({"Type": Name("OCG"), "Name": PdfString(b"off")})
        setup.oc = (on, off)
        return {"Properties": {"L1": on, "L2": off}}
    b = PB()
    r = setup(b)
    on, off = setup.oc
    c = b"/OC /L1 BDC 1 0 0 rg 10 10 80 80 re f EMC /OC /L2 BDC 0 0 1 rg 100 10 80 80 re f EMC 0 g 10 120 30 30 re f"
    cc = b.add({}, stream=c)
    pages = b.reserve()
    p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 200, 200], "Contents": cc, "Resources": r})
    b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
    return b.finish(pages, {"OCProperties": {"OCGs": [on, off], "D": {"OFF": [off]}}})


@case
def text_state():
    def setup(b):
        return {"Font": {"F1": b.add(std_font("Helvetica")), "F2": b.add(std_font("Times-Roman")), "F3": b.add(std_font("Courier"))}}
    return one("""
BT /F1 18 Tf 10 170 Td (Helvetica Tc Tw) Tj ET
BT /F1 12 Tf 2 Tc 10 150 Td (char space) Tj 0 Tc 10 Tw ( word space here) Tj ET
BT /F2 14 Tf 10 130 Td 150 Tz (squeezed Tz) Tj 100 Tz 5 Ts ( rise) Tj 0 Ts ET
BT /F3 10 Tf 14 TL 10 110 Td (line one) Tj T* (line two) Tj (line three) ' ET
BT /F1 20 Tf 1 Tr 1 0 0 RG 10 50 Td (Outline) Tj 2 Tr 0 0 1 rg 100 0 Td (Both) Tj ET
BT /F1 12 Tf 3 Tr 10 30 Td (invisible text) Tj ET
BT /F1 12 Tf 0 Tr 0 g 10 15 Td [(K) 120 (ern) -300 (ed) 50 (TJ)] TJ ET
""", setup=setup)


@case
def type3_font():
    def setup(b):
        A = b.add({}, stream=b"1000 0 0 0 750 750 d1 0 0 750 750 re f")
        B = b.add({}, stream=b"1000 0 d0 1 0 0 rg 0 0 m 750 0 l 375 750 l f")
        f = b.add({"Type": Name("Font"), "Subtype": Name("Type3"), "FontBBox": [0, 0, 750, 750], "FontMatrix": [0.001, 0, 0, 0.001, 0, 0],
                   "CharProcs": {"sq": A, "tri": B}, "Encoding": {"Type": Name("Encoding"), "Differences": [97, Name("sq"), Name("tri")]},
                   "FirstChar": 97, "LastChar": 98, "Widths": [1000, 1000], "Resources": {}})
        return {"Font": {"T3": f}}
    return one("0 0.5 0 rg BT /T3 40 Tf 10 100 Td (abab) Tj ET 0 0 1 rg BT /T3 20 Tf 10 40 Td (aab) Tj ET", setup=setup)


@case
def inline_and_misc():
    return one("""
q 1 0 0 1 100 100 cm 0.5 0 0 rg 0 0 m 50 0 l 50 50 l 0 50 l f Q
10 10 m 60 10 60 60 10 60 c h 0 0.5 0.5 rg f
70 70 m 120 70 150 120 150 120 v 150 120 190 190 y S
1 w 0 0 0 RG 10 190 m 190 190 l 190 150 l S
""")


@case
def tiny_and_degenerate():
    return one("""
0 0 0 rg 10 10 0 0 re f 0 w 20 20 m 20 20 l S 1 J 6 w 40 40 m 40 40 l S 2 J 60 40 m 60 40 l S
q 0 0 0 0 0 0 cm 0 0 100 100 re f Q
1 0 0 rg 100 100 m 100 100 l f
0 0 1 rg 120 120 50 0 re f
5 w 0 0 1 RG 120 150 m 170 150 l h S
""")


def build(name):
    return CASES[name]()


@case
def jpeg_images():
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    names = [("jpg_420", "DeviceRGB"), ("jpg_444", "DeviceRGB"), ("jpg_prog", "DeviceRGB"), ("jpg_gray", "DeviceGray"), ("jpg_cmyk", "DeviceCMYK"), ("jpg_rst", "DeviceRGB")]

    def setup(b):
        xo = {}
        for i, (n, cs) in enumerate(names):
            data = open(os.path.join(fx, n + ".jpg"), "rb").read()
            d = {"Type": Name("XObject"), "Subtype": Name("Image"), "Width": 96, "Height": 64, "ColorSpace": Name(cs), "BitsPerComponent": 8, "Filter": Name("DCTDecode")}
            if cs == "DeviceCMYK":
                d["Decode"] = [1, 0, 1, 0, 1, 0, 1, 0]
            xo[f"J{i}"] = b.add(d, stream=data)
        return {"XObject": xo}
    cont = "".join(f"q 90 0 0 60 {5 + (i % 2) * 100} {135 - (i // 2) * 65} cm /J{i} Do Q\n" for i in range(len(names)))
    return one(cont, setup=setup)


INTER = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
TYPE1 = "/usr/share/fonts/X11/Type1/c0419bt_.pfb"


def _sfnt_table(data, tag):
    n = struct.unpack(">H", data[4:6])[0]
    for i in range(n):
        t, _, o, l = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if t == tag:
            return data[o:o + l]


@case
def cff_fonts():
    """Inter (OpenType/CFF) embedded three ways: bare Type1C simple font, OpenType simple font, CID-keyed OpenType."""
    if not os.path.exists(INTER):
        raise FileNotFoundError(INTER)
    otf = open(INTER, "rb").read()
    cff = _sfnt_table(otf, b"CFF ")

    def setup(b):
        from quire.truetype import TrueTypeFont
        tt = TrueTypeFont(otf)
        cm = tt.cmaps()[(3, 1)]
        widths = [int(round((tt.advance(cm.get(c, 0)) or 0) * 1000 / tt.units_per_em)) for c in range(32, 127)]
        desc = lambda key, ref: {"Type": Name("FontDescriptor"), "FontName": Name("Inter"), "Flags": 32, "FontBBox": [-100, -300, 1200, 1000],
                                 "ItalicAngle": 0, "Ascent": 900, "Descent": -200, "CapHeight": 700, "StemV": 80, key: ref}
        ff1 = b.add({"Subtype": Name("Type1C")}, stream=cff, compress=True)
        f1 = b.add({"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name("Inter"), "FirstChar": 32, "LastChar": 126, "Widths": widths,
                    "Encoding": Name("WinAnsiEncoding"), "FontDescriptor": b.add(desc("FontFile3", ff1))})
        ff2 = b.add({"Subtype": Name("OpenType")}, stream=otf, compress=True)
        f2 = b.add({"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name("Inter"), "FirstChar": 32, "LastChar": 126, "Widths": widths,
                    "Encoding": Name("WinAnsiEncoding"), "FontDescriptor": b.add(desc("FontFile3", ff2))})
        cid = b.add({"Type": Name("Font"), "Subtype": Name("CIDFontType0"), "BaseFont": Name("Inter"), "CIDSystemInfo": {"Registry": PdfString(b"Adobe"), "Ordering": PdfString(b"Identity"), "Supplement": 0},
                     "FontDescriptor": b.add(desc("FontFile3", ff2)), "DW": 600})
        f3 = b.add({"Type": Name("Font"), "Subtype": Name("Type0"), "BaseFont": Name("Inter"), "Encoding": Name("Identity-H"), "DescendantFonts": [cid]})
        setup.gids = [cm[ord(c)] for c in "Hamburgefonts"]
        return {"Font": {"F1": f1, "F2": f2, "F3": f3}}
    b = PB()
    res = setup(b)
    hexs = "".join("%04X" % g for g in setup.gids)
    c = f"BT /F1 20 Tf 10 160 Td (Hamburgefonts: Type1C 0123) Tj ET BT /F2 14 Tf 10 120 Td (OpenType simple font, Quartz!) Tj ET BT /F3 18 Tf 10 80 Td <{hexs}> Tj ET"
    cc = b.add({}, stream=c.encode())
    pages = b.reserve()
    p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 300, 200], "Contents": cc, "Resources": res})
    b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
    return b.finish(pages)


@case
def type1_fonts():
    """A real Type 1 program (Bitstream Charter PFB) embedded as /FontFile with Differences encoding."""
    if not os.path.exists(TYPE1):
        raise FileNotFoundError(TYPE1)
    raw = open(TYPE1, "rb").read()
    # unwrap PFB segments into one cleartext+binary stream as PDF wants, record Length1/2/3
    segs = []
    p = 0
    while p < len(raw) and raw[p] == 0x80 and raw[p + 1] != 3:
        ln = struct.unpack("<I", raw[p + 2:p + 6])[0]
        segs.append((raw[p + 1], raw[p + 6:p + 6 + ln]))
        p += 6 + ln
    l1 = len(segs[0][1]); l2 = len(segs[1][1]); l3 = sum(len(s[1]) for s in segs[2:])
    prog = b"".join(s[1] for s in segs)

    def setup(b):
        ff = b.add({"Length1": l1, "Length2": l2, "Length3": l3}, stream=prog, compress=True)
        import re
        afm = open(TYPE1.replace(".pfb", ".afm")).read()
        wx = {m.group(2): int(m.group(1)) for m in re.finditer(r"WX\s+(\d+)\s*;\s*N\s+(\S+)", afm)}
        from quire.glyphlist import WIN_ANSI, unicode_to_name
        widths = [wx.get(unicode_to_name(WIN_ANSI[c]), 500) if c in WIN_ANSI else 0 for c in range(32, 256)]
        desc = b.add({"Type": Name("FontDescriptor"), "FontName": Name("Charter"), "Flags": 32, "FontBBox": [-100, -300, 1200, 1000], "ItalicAngle": 0,
                      "Ascent": 900, "Descent": -200, "CapHeight": 700, "StemV": 80, "FontFile": ff})
        f = b.add({"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name("Charter"), "FirstChar": 32, "LastChar": 255, "Widths": widths,
                   "Encoding": Name("WinAnsiEncoding"), "FontDescriptor": desc})
        return {"Font": {"F1": f}}
    return one("BT /F1 22 Tf 10 150 Td (Type 1 Charter: AVAWA fi) Tj 0 -30 Td (Caf\xe9 \xfcber na\xefve \x93quoted\x94) Tj /F1 12 Tf 0 -30 Td (The quick brown fox jumps over the lazy dog 0123456789) Tj ET", setup=setup)


@case
def annotations():
    def setup(b):
        stamp = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 100, 40], "Resources": {"Font": {"F1": b.add(std_font("Helvetica"))}}},
                      stream=b"1 0.9 0.9 rg 0 0 100 40 re f 0.8 0 0 RG 3 w 1.5 1.5 97 37 re S 0.8 0 0 rg BT /F1 18 Tf 10 12 Td (DRAFT) Tj ET")
        on = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 20, 20]}, stream=b"0 0.6 0 rg 0 0 20 20 re f 1 g 4 4 12 12 re f")
        off = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 20, 20]}, stream=b"0.6 g 0 0 20 20 re f")
        rot = b.add({"Type": Name("XObject"), "Subtype": Name("Form"), "BBox": [0, 0, 10, 10], "Matrix": [0, 1, -1, 0, 0, 0]}, stream=b"0 0 1 rg 0 0 10 4 re f 1 0 0 rg 0 4 10 6 re f")
        a1 = b.add({"Type": Name("Annot"), "Subtype": Name("Stamp"), "Rect": [20, 130, 160, 190], "AP": {"N": stamp}, "F": 4})
        a2 = b.add({"Type": Name("Annot"), "Subtype": Name("Widget"), "Rect": [20, 80, 50, 110], "AS": Name("Yes"), "AP": {"N": {"Yes": on, "Off": off}}, "F": 4})
        a3 = b.add({"Type": Name("Annot"), "Subtype": Name("Widget"), "Rect": [70, 80, 100, 110], "AS": Name("Off"), "AP": {"N": {"Yes": on, "Off": off}}})
        a4 = b.add({"Type": Name("Annot"), "Subtype": Name("Stamp"), "Rect": [120, 80, 190, 110], "AP": {"N": stamp}, "F": 2})   # hidden
        a5 = b.add({"Type": Name("Annot"), "Subtype": Name("Stamp"), "Rect": [20, 20, 80, 60], "AP": {"N": rot}})
        a6 = b.add({"Type": Name("Annot"), "Subtype": Name("Link"), "Rect": [100, 20, 190, 60], "Border": [0, 0, 1]})   # no AP: nothing drawn
        return {"_annots": [a1, a2, a3, a4, a5, a6]}
    b = PB()
    r = setup(b)
    an = r.pop("_annots")
    c = b.add({}, stream=b"0.95 0.95 1 rg 0 0 200 200 re f")
    pages = b.reserve()
    p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 200, 200], "Contents": c, "Resources": {}, "Annots": an})
    b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
    return b.finish(pages)
