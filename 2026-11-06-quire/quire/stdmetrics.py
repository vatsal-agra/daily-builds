"""Advance widths (1/1000 em) for the base-14 fonts, used when a PDF omits /Widths for a
non-embedded font. ASCII only; Bold/Italic Times and Bold-Oblique variants reuse the nearest table
(an approximation — documented in the README)."""
_ASCII = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"

_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
    [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722,
     778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500,
     556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500,
     500, 500, 334, 260, 334, 584]
_HELV_B = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
    [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722,
     778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556,
     611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556,
     556, 500, 389, 280, 389, 584]
_TIMES = [250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278] + [500] * 10 + \
    [278, 278, 564, 564, 564, 444, 921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722,
     722, 556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500, 333, 444, 500, 444,
     500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500, 500, 500, 333, 389, 278, 500, 500, 722, 500,
     500, 444, 480, 200, 480, 541]
_COURIER = [600] * 95

TABLES = {"helvetica": dict(zip(_ASCII, _HELV)), "helvetica-bold": dict(zip(_ASCII, _HELV_B)),
          "times": dict(zip(_ASCII, _TIMES)), "courier": dict(zip(_ASCII, _COURIER))}


def std_widths(basefont):
    """Return {char: width} for a recognised base-14 style name, else None."""
    n = basefont.lower().replace(" ", "").replace(",", "-")
    bold = "bold" in n
    if n.startswith(("helvetica", "arial")):
        return TABLES["helvetica-bold" if bold else "helvetica"]
    if n.startswith(("times", "timesnewroman")):
        return TABLES["times"]
    if n.startswith("courier"):
        return TABLES["courier"]
    return None
