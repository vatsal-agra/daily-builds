"""Font metrics.

Galley lays type using genuine Adobe Font Metrics (AFM) character widths for the
PostScript base-14 fonts.  The numbers below are the published ``WX`` advance
widths (in 1000-unit em space) for Times-Roman and Helvetica, and the constant
600 for the monospaced Courier.  They are real data, not invented values, so the
layout Galley computes matches what a PostScript/PDF renderer would produce.

A :class:`Font` turns characters and strings into advance widths at a chosen
point size, and exposes the natural inter-word space width used to build glue.
"""

from __future__ import annotations

# --- Times-Roman advance widths (AFM WX, /1000 em) for printable ASCII -------
# Source: Adobe Core Font Set AFM (Times-Roman.afm).
_TIMES = {
    " ": 250, "!": 333, '"': 408, "#": 500, "$": 500, "%": 833, "&": 778,
    "'": 180, "(": 333, ")": 333, "*": 500, "+": 564, ",": 250, "-": 333,
    ".": 250, "/": 278, "0": 500, "1": 500, "2": 500, "3": 500, "4": 500,
    "5": 500, "6": 500, "7": 500, "8": 500, "9": 500, ":": 278, ";": 278,
    "<": 564, "=": 564, ">": 564, "?": 444, "@": 921, "A": 722, "B": 667,
    "C": 667, "D": 722, "E": 611, "F": 556, "G": 722, "H": 722, "I": 333,
    "J": 389, "K": 722, "L": 611, "M": 889, "N": 722, "O": 722, "P": 556,
    "Q": 722, "R": 667, "S": 556, "T": 611, "U": 722, "V": 722, "W": 944,
    "X": 722, "Y": 722, "Z": 611, "[": 333, "\\": 278, "]": 333, "^": 469,
    "_": 500, "`": 333, "a": 444, "b": 500, "c": 444, "d": 500, "e": 444,
    "f": 333, "g": 500, "h": 500, "i": 278, "j": 278, "k": 500, "l": 278,
    "m": 778, "n": 500, "o": 500, "p": 500, "q": 500, "r": 333, "s": 389,
    "t": 278, "u": 500, "v": 500, "w": 722, "x": 500, "y": 500, "z": 444,
    "{": 480, "|": 200, "}": 480, "~": 541,
}

# --- Helvetica advance widths (AFM WX, /1000 em) -----------------------------
# Source: Adobe Core Font Set AFM (Helvetica.afm).
_HELVETICA = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278, "0": 556, "1": 556, "2": 556, "3": 556, "4": 556,
    "5": 556, "6": 556, "7": 556, "8": 556, "9": 556, ":": 278, ";": 278,
    "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "A": 667, "B": 667,
    "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278,
    "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469,
    "_": 556, "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556,
    "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500, "l": 222,
    "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500,
    "t": 278, "u": 556, "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}

# Average width used as a fallback for any character outside the table (the
# AFM tables only cover ASCII; accented letters fall back to this).
_TIMES_DEFAULT = 500
_HELVETICA_DEFAULT = 556

#: Recognised font family names mapped to their CSS generic + metric source.
_FAMILIES = {
    "times": ("Times-Roman", "'Times New Roman', Times, serif", _TIMES, _TIMES_DEFAULT),
    "helvetica": ("Helvetica", "Helvetica, Arial, sans-serif", _HELVETICA, _HELVETICA_DEFAULT),
    "courier": ("Courier", "'Courier New', Courier, monospace", None, 600),
}


class Font:
    """An AFM font at a fixed point size.

    Widths are returned in *points* (1 pt = 1/72 inch), the unit used throughout
    Galley for line widths and glue.
    """

    def __init__(self, family: str = "times", size: float = 10.0):
        key = family.lower()
        if key not in _FAMILIES:
            raise ValueError(
                f"unknown font family {family!r}; "
                f"choose from {', '.join(sorted(_FAMILIES))}"
            )
        self.family = key
        self.psname, self.css, self._table, self._default = _FAMILIES[key]
        self.size = float(size)
        if self.size <= 0:
            raise ValueError("font size must be positive")
        self.monospace = self._table is None

    def char_width(self, ch: str) -> float:
        """Advance width of a single character in points."""
        if self._table is None:  # Courier: fixed pitch
            units = self._default
        else:
            units = self._table.get(ch, self._default)
        return units * self.size / 1000.0

    def width(self, text: str) -> float:
        """Advance width of a string in points (sum of character advances)."""
        if self._table is None:
            return len(text) * self._default * self.size / 1000.0
        t = self._table
        d = self._default
        total = 0
        for ch in text:
            total += t.get(ch, d)
        return total * self.size / 1000.0

    @property
    def space_width(self) -> float:
        """Natural width of an inter-word space in points."""
        return self.char_width(" ")

    def __repr__(self) -> str:
        return f"Font({self.family!r}, size={self.size})"


def available_families() -> list[str]:
    return sorted(_FAMILIES)
