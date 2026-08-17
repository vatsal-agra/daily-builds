"""A bundled, self-consistent font-metric model for text layout.

Folio does not rasterize real font glyphs (no FreeType, no font files), so
it cannot reproduce the exact per-glyph advance widths a real browser's font
rasterizer would use -- matching Chromium pixel-for-pixel on *text* geometry
is not attempted, and Folio says so plainly rather than pretending
otherwise (see PLAN.md / REVIEW.md). What it does instead: a fixed
average-advance-width-per-character model, applied *consistently* by both
the line-breaking algorithm and the paint stage, so text layout is fully
deterministic and independently verifiable (against a brute-force
reference line-breaker using the same metric -- see tests/test_layout_inline.py)
rather than silently approximate.
"""

# Advance width as a fraction of font-size. Folio paints with a monospace
# font (see paint.py) specifically so this fixed-advance assumption is
# actually true of the rendered glyphs, not just of the layout math --
# 0.6em is "Courier New"'s real advance width, bold included (monospace
# fonts keep the same advance for bold by design).
CHAR_ADVANCE_RATIO = 0.6
BOLD_ADVANCE_RATIO = 0.6


def char_width(font_size_px, bold=False):
    ratio = BOLD_ADVANCE_RATIO if bold else CHAR_ADVANCE_RATIO
    return font_size_px * ratio


def measure_text(text, font_size_px, bold=False):
    return len(text) * char_width(font_size_px, bold=bold)


def default_line_height(font_size_px):
    return font_size_px * 1.2


def resolve_line_height(line_height_value, font_size_px):
    """`line_height_value` is either 'normal', a float (absolute px, from a
    <length> value already resolved during cascade), or ('multiple', n)."""
    if line_height_value == "normal":
        return default_line_height(font_size_px)
    if isinstance(line_height_value, tuple) and line_height_value[0] == "multiple":
        return line_height_value[1] * font_size_px
    if isinstance(line_height_value, (int, float)):
        return float(line_height_value)
    return default_line_height(font_size_px)
