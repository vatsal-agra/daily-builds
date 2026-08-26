"""A small, hand-authored proportional font-metrics table.

Real browsers measure text against the actual glyph outlines of an
installed font. We don't have a font-rasterizer, so instead we use a
metrics table of *relative advance widths* (as a fraction of font-size) —
the same idea as the AFM metrics Galley (2026-06-18) used for real
typesetting, just a compact approximation instead of a shipped font file.
Values are calibrated against common sans-serif proportions (narrow
punctuation/'i'/'l', wide 'm'/'w'/capitals, ~0.5em average lowercase).
"""

_NARROW = "il.,:;'!|Ijt"
_WIDE = "mwMW@%"
_MED_WIDE = "ABCDEFGHKNOPQRSUVXYZ0123456789"

# Deliberately generous vs. a typical sans-serif's real metrics: these
# numbers drive both our own layout AND the literal SVG <text> a real
# renderer draws, so underestimating causes visible glyph overlap while
# overestimating just reads as slightly loose spacing — pick the safer
# error. (The Chromium differential oracle already uses a generous
# tolerance on text-driven box sizes for exactly this reason — see
# oracle/diff.cjs.)
DEFAULT_ADVANCE = 0.62
SPACE_ADVANCE = 0.32

_TABLE = {}
for ch in _NARROW:
    _TABLE[ch] = 0.32
for ch in _WIDE:
    _TABLE[ch] = 0.95
for ch in _MED_WIDE:
    _TABLE[ch] = 0.72
for ch in "abcdeghknopqsuvxyz":
    _TABLE[ch] = 0.56
for ch in "fr()[]{}\"-+=/*_~^<>?":
    _TABLE[ch] = 0.46
_TABLE[" "] = SPACE_ADVANCE
_TABLE["\t"] = SPACE_ADVANCE * 4

# Monospace advance is uniform, used when font-family requests it. Measured
# directly against real Chromium's default `monospace` generic family at
# an explicit font-size (oracle/run_diff.py, testpages/05_inline_block.html)
# came out ~0.602em — note this must be measured at an *explicit*
# font-size: Chromium applies its own "fixed-width font size" UI
# preference (default 13px, not the standard 16px) to unset-size
# monospace text, which corrupted an earlier version of this measurement.
# 0.62 keeps a slight safety margin above the real ~0.602 so our own SVG
# text (rendered by a real browser too) never overlaps.
MONOSPACE_ADVANCE = 0.62


def char_advance(ch, monospace=False):
    if monospace:
        return MONOSPACE_ADVANCE
    return _TABLE.get(ch, DEFAULT_ADVANCE)


def text_width(text, font_size, monospace=False):
    """Width in px of `text` set at `font_size`, no kerning (matches the
    per-character advance model real 'sum of advances' text shaping uses
    at this level of fidelity)."""
    return sum(char_advance(c, monospace) for c in text) * font_size


def is_monospace(font_family):
    if not font_family:
        return False
    fam = font_family.lower()
    return "mono" in fam or "courier" in fam or "consolas" in fam
