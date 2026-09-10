"""Parsing/resolving raw CSS value strings into usable Python values:
lengths (px/em/%), colors (named/#hex/rgb()/rgba()), and the small set of
keyword properties this engine understands. Also defines which properties
inherit and their initial values, for the cascade."""

import re

NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "navy": (0, 0, 128), "teal": (0, 128, 128),
    "maroon": (128, 0, 0), "olive": (128, 128, 0), "lime": (0, 255, 0),
    "aqua": (0, 255, 255), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255), "indigo": (75, 0, 130), "gold": (255, 215, 0),
    "coral": (255, 127, 80), "salmon": (250, 128, 114), "khaki": (240, 230, 140),
    "crimson": (220, 20, 60), "darkgreen": (0, 100, 0), "darkblue": (0, 0, 139),
    "lightblue": (173, 216, 230), "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211), "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169), "beige": (245, 245, 220),
    "ivory": (255, 255, 240), "tomato": (255, 99, 71),
    "steelblue": (70, 130, 180), "slategray": (112, 128, 144),
    "transparent": (0, 0, 0, 0),
}

INHERITED_PROPERTIES = {
    "color", "font-family", "font-size", "font-weight", "font-style",
    "line-height", "text-align", "list-style-type", "visibility",
    "white-space",
}

INITIAL_VALUES = {
    "display": "inline",
    "position": "static",
    "color": "#000000",
    "background-color": "transparent",
    "font-size": "16px",
    "font-weight": "normal",
    "font-style": "normal",
    "font-family": "sans-serif",
    "line-height": "normal",
    "text-align": "left",
    "width": "auto",
    "height": "auto",
    "margin-top": "0px", "margin-right": "0px",
    "margin-bottom": "0px", "margin-left": "0px",
    "padding-top": "0px", "padding-right": "0px",
    "padding-bottom": "0px", "padding-left": "0px",
    "border-top-width": "0px", "border-right-width": "0px",
    "border-bottom-width": "0px", "border-left-width": "0px",
    "border-top-style": "none", "border-right-style": "none",
    "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "#000000", "border-right-color": "#000000",
    "border-bottom-color": "#000000", "border-left-color": "#000000",
    "list-style-type": "disc",
    "white-space": "normal",
    "visibility": "visible",
    "flex-direction": "row",
    "justify-content": "flex-start",
    "align-items": "stretch",
    "flex-grow": "0",
    "flex-shrink": "1",
    "flex-basis": "auto",
}

_LEN_RE = re.compile(r"^([+-]?(?:\d*\.\d+|\d+))([a-zA-Z%]*)$")


class Length:
    """A resolved length: either an absolute px value or a percentage of
    some later-known base."""

    __slots__ = ("px", "percent", "auto")

    def __init__(self, px=None, percent=None, auto=False):
        self.px = px
        self.percent = percent
        self.auto = auto

    def resolve(self, base_px, auto_value=0.0):
        if self.auto:
            return auto_value
        if self.percent is not None:
            return base_px * self.percent / 100.0
        return self.px if self.px is not None else 0.0

    def __repr__(self):
        if self.auto:
            return "auto"
        if self.percent is not None:
            return f"{self.percent}%"
        return f"{self.px}px"


def parse_length(value, font_size=16.0):
    if value is None:
        return Length(auto=True)
    value = value.strip()
    if value == "auto" or value == "":
        return Length(auto=True)
    if value == "0":
        return Length(px=0.0)
    m = _LEN_RE.match(value)
    if not m:
        return Length(auto=True)
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "%":
        return Length(percent=num)
    if unit in ("px", ""):
        return Length(px=num)
    if unit == "em":
        return Length(px=num * font_size)
    if unit == "rem":
        return Length(px=num * 16.0)
    if unit == "pt":
        return Length(px=num * 96.0 / 72.0)
    return Length(px=num)


def parse_color(value, default=(0, 0, 0, 255)):
    if not value:
        return default
    value = value.strip().lower()
    if value in NAMED_COLORS:
        c = NAMED_COLORS[value]
        return c if len(c) == 4 else (*c, 255)
    if value.startswith("#"):
        h = value[1:]
        try:
            if len(h) == 3:
                r, g, b = (int(c * 2, 16) for c in h)
                return (r, g, b, 255)
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            if len(h) == 8:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
        except ValueError:
            return default
        return default
    m = re.match(r"rgba?\(\s*([^)]+)\)", value)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            r, g, b = (int(float(p)) for p in parts[:3])
            a = int(float(parts[3]) * 255) if len(parts) > 3 else 255
            return (r, g, b, a)
        except ValueError:
            return default
    return default


def parse_font_weight(value):
    value = (value or "normal").strip().lower()
    if value in ("bold", "bolder"):
        return 700
    if value == "normal":
        return 400
    try:
        return int(value)
    except ValueError:
        return 400


def is_display_none(computed):
    return computed.get("display", "inline") == "none"
