"""CSS value parsing: lengths, percentages, and colors."""

import re

AUTO = "auto"

_LENGTH_RE = re.compile(r"^(-?[0-9]*\.?[0-9]+)(px|em|rem|%)?$")

# CSS1 keyword colors plus the small set of extended names that show up
# constantly in real-world markup and test fixtures.
NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "lime": (0, 255, 0), "aqua": (0, 255, 255),
    "teal": (0, 128, 128), "navy": (0, 0, 128), "fuchsia": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "gold": (255, 215, 0), "indigo": (75, 0, 130),
    "coral": (255, 127, 80), "salmon": (250, 128, 114), "khaki": (240, 230, 140),
    "orchid": (218, 112, 214), "tan": (210, 180, 140), "crimson": (220, 20, 60),
    "chocolate": (210, 105, 30), "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "lightblue": (173, 216, 230), "lightgreen": (144, 238, 144),
    "darkblue": (0, 0, 139), "darkgreen": (0, 100, 0), "darkred": (139, 0, 0),
    "skyblue": (135, 206, 235), "steelblue": (70, 130, 180), "tomato": (255, 99, 71),
    "slategray": (112, 128, 144), "slategrey": (112, 128, 144),
    "whitesmoke": (245, 245, 245), "gainsboro": (220, 220, 220),
    "beige": (245, 245, 220), "ivory": (255, 255, 240), "azure": (240, 255, 255),
    "lavender": (230, 230, 250), "plum": (221, 160, 221), "violet": (238, 130, 238),
    "chartreuse": (127, 255, 0), "turquoise": (64, 224, 208), "seagreen": (46, 139, 87),
    "firebrick": (178, 34, 34), "royalblue": (65, 105, 225), "midnightblue": (25, 25, 112),
    "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "peru": (205, 133, 63), "sienna": (160, 82, 45), "wheat": (245, 222, 179),
    "hotpink": (255, 105, 180), "deeppink": (255, 20, 147), "orangered": (255, 69, 0),
}


class Length:
    """A resolved absolute length in px, OR a pending percentage, OR auto."""

    __slots__ = ("kind", "value")  # kind in ('px', 'percent', 'auto')

    def __init__(self, kind, value=0.0):
        self.kind = kind
        self.value = value

    @property
    def is_auto(self):
        return self.kind == "auto"

    @property
    def is_percent(self):
        return self.kind == "percent"

    def resolve(self, containing_block_size, auto_value=0.0):
        """Resolve against a containing-block dimension. `auto` resolves to
        `auto_value` (callers that need a real number for a non-auto-capable
        property, e.g. padding, pass 0.0; callers doing width/margin math
        that treats auto specially check `.is_auto` themselves first)."""
        if self.kind == "px":
            return self.value
        if self.kind == "percent":
            return containing_block_size * self.value / 100.0
        return auto_value

    def __repr__(self):
        if self.kind == "auto":
            return "auto"
        if self.kind == "percent":
            return "%g%%" % self.value
        return "%gpx" % self.value


ZERO = Length("px", 0.0)
AUTO_LENGTH = Length("auto")


def parse_length(text, font_size_px=16.0, allow_auto=True, allow_percent=True):
    """Parse a <length> | <percentage> | auto value. em/rem resolve against
    `font_size_px` immediately (rem uses the same value here -- Folio
    doesn't model a separate root font-size beyond the UA default). Returns
    a Length, or None if unparseable (caller falls back to the initial
    value)."""
    if text is None:
        return None
    text = text.strip()
    if allow_auto and text == "auto":
        return Length("auto")
    if text in ("0", "0px", "0%", "0em"):
        return Length("px", 0.0)
    m = _LENGTH_RE.match(text)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "px"
    if unit == "%":
        if not allow_percent:
            return None
        return Length("percent", num)
    if unit in ("em", "rem"):
        return Length("px", num * font_size_px)
    return Length("px", num)


def parse_color(text, current_color=(0, 0, 0)):
    """Parse a <color>: #hex, #hexhex, rgb()/rgba(), a named color, or the
    'currentColor' / 'transparent' keywords. Returns (r, g, b, a) with a in
    [0, 255], or None if unparseable."""
    if text is None:
        return None
    text = text.strip()
    low = text.lower()
    if low == "transparent":
        return (0, 0, 0, 0)
    if low == "currentcolor":
        return (current_color[0], current_color[1], current_color[2], 255)
    if text.startswith("#"):
        hexpart = text[1:]
        if len(hexpart) == 3:
            try:
                r = int(hexpart[0] * 2, 16)
                g = int(hexpart[1] * 2, 16)
                b = int(hexpart[2] * 2, 16)
                return (r, g, b, 255)
            except ValueError:
                return None
        if len(hexpart) == 6:
            try:
                r = int(hexpart[0:2], 16)
                g = int(hexpart[2:4], 16)
                b = int(hexpart[4:6], 16)
                return (r, g, b, 255)
            except ValueError:
                return None
        return None
    m = re.match(r"rgba?\(\s*([^)]+)\)", text, re.IGNORECASE)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            r = _channel(parts[0])
            g = _channel(parts[1])
            b = _channel(parts[2])
            a = float(parts[3]) if len(parts) > 3 else 1.0
            return (r, g, b, max(0, min(255, round(a * 255))))
        except (ValueError, IndexError):
            return None
    if low in NAMED_COLORS:
        r, g, b = NAMED_COLORS[low]
        return (r, g, b, 255)
    return None


def _channel(text):
    text = text.strip()
    if text.endswith("%"):
        return max(0, min(255, round(float(text[:-1]) / 100.0 * 255)))
    return max(0, min(255, round(float(text))))


def color_to_css(rgba):
    r, g, b, a = rgba
    if a >= 255:
        return "rgb(%d,%d,%d)" % (r, g, b)
    return "rgba(%d,%d,%d,%.3f)" % (r, g, b, a / 255.0)
