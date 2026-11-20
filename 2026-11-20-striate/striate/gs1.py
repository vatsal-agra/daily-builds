"""GS1-128: application-identifier (AI) parsing and construction on top of Code 128 + FNC1."""
import re
from dataclasses import dataclass
from datetime import date

from .symbologies.code128 import FNC1
from .symbologies import ean

# AI -> (name, fixed_length or None, max_length, kind)   kind: 'num' digits only, 'any' GS1 set 82 (we accept printable ASCII)
_FIXED = {"00": ("SSCC", 18), "01": ("GTIN", 14), "02": ("CONTENT", 14), "11": ("PROD DATE", 6), "12": ("DUE DATE", 6),
          "13": ("PACK DATE", 6), "15": ("BEST BEFORE", 6), "16": ("SELL BY", 6), "17": ("USE BY", 6), "20": ("VARIANT", 2),
          "410": ("SHIP TO LOC", 13), "411": ("BILL TO", 13), "414": ("LOC NO", 13)}
_VAR = {"10": ("BATCH/LOT", 20), "21": ("SERIAL", 20), "22": ("CPV", 20), "30": ("VAR. COUNT", 8), "37": ("COUNT", 8),
        "400": ("ORDER NUMBER", 30), "420": ("SHIP TO POST", 20), "240": ("ADDITIONAL ID", 30), "241": ("CUST. PART NO", 30),
        **{str(n): ("INTERNAL", 30) for n in range(91, 100)}}
_NUM_ONLY = {"30", "37"}
for _n in range(10):
    _FIXED[f"310{_n}"] = ("NET WEIGHT (kg)", 6); _FIXED[f"320{_n}"] = ("NET WEIGHT (lb)", 6)
    _VAR[f"390{_n}"] = ("AMOUNT", 15)
DATE_AIS = {"11", "12", "13", "15", "16", "17"}


class GS1Error(ValueError):
    pass


@dataclass
class Field:
    ai: str
    name: str
    value: str
    meaning: str = ""      # human interpretation (ISO date, decimal weight...)

    def __str__(self):
        return f"({self.ai}){self.value}"


def _lookup(s, i):
    for ln in (2, 3, 4):
        ai = s[i:i + ln]
        if ai in _FIXED or ai in _VAR:
            return ai
    return None


def _interpret(ai, value):
    if ai in DATE_AIS:
        yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:])
        if not 1 <= mm <= 12 or dd > 31:
            raise GS1Error(f"AI ({ai}): invalid date {value!r}")
        year = 2000 + yy if yy < 51 else 1900 + yy       # GS1 century rule (simplified: 00-50 -> 20xx)
        if dd == 0:
            return f"{year:04d}-{mm:02d} (day unspecified)"
        try:
            date(year, mm, dd)
        except ValueError:
            raise GS1Error(f"AI ({ai}): impossible date {value!r}")
        return f"{year:04d}-{mm:02d}-{dd:02d}"
    if ai in ("01", "02"):
        if not ean.verify(value):
            raise GS1Error(f"AI ({ai}): bad GTIN check digit in {value!r}")
        return "GTIN-14"
    if ai == "00":
        if not ean.verify(value):
            raise GS1Error(f"SSCC check digit invalid in {value!r}")
        return "SSCC-18"
    if ai[:3] in ("310", "320") and len(ai) == 4:
        n = int(ai[3]); v = int(value)
        return f"{v / (10 ** n):.{n}f}" + (" kg" if ai.startswith("310") else " lb")
    return ""


def parse(text):
    """Parse decoded Code 128 text (leading FNC1 required) into [Field]. Raises GS1Error."""
    if not text.startswith(FNC1):
        raise GS1Error("not a GS1-128 symbol (no leading FNC1)")
    s = text[1:]
    out, i = [], 0
    while i < len(s):
        ai = _lookup(s, i)
        if ai is None:
            raise GS1Error(f"unknown application identifier at {s[i:i + 4]!r}")
        i += len(ai)
        if ai in _FIXED:
            name, ln = _FIXED[ai]
            val = s[i:i + ln]
            if len(val) != ln or not val.isdigit():
                raise GS1Error(f"AI ({ai}) needs exactly {ln} digits, got {val!r}")
            i += ln
        else:
            name, mx = _VAR[ai]
            j = i
            while j < len(s) and s[j] not in (FNC1, "\x1d") and j - i < mx + 1:
                j += 1
            val = s[i:j]
            if not val or len(val) > mx:
                raise GS1Error(f"AI ({ai}) value length {len(val)} outside 1..{mx}")
            if ai in _NUM_ONLY and not val.isdigit():
                raise GS1Error(f"AI ({ai}) must be numeric")
            i = j + 1 if j < len(s) and s[j] in (FNC1, "\x1d") else j
        out.append(Field(ai, name, val, _interpret(ai, val)))
    if not out:
        raise GS1Error("empty GS1-128 payload")
    return out


_HUMAN = re.compile(r"\((\d{2,4})\)([^(]*)")


def build(human):
    """'(01)09501101530003(17)250101(10)LOT42' -> Code 128 text with FNC1 prefix/separators."""
    human = human.strip()
    pairs = _HUMAN.findall(human)
    if not pairs or "".join(f"({a}){v}" for a, v in pairs) != human:
        raise GS1Error("expected human-readable form like (01)09501101530003(10)ABC")
    parts = []
    for k, (ai, val) in enumerate(pairs):
        if ai in _FIXED:
            ln = _FIXED[ai][1]
            if len(val) != ln or not val.isdigit():
                raise GS1Error(f"AI ({ai}) needs exactly {ln} digits")
            parts.append(ai + val)
        elif ai in _VAR:
            mx = _VAR[ai][1]
            if not val or len(val) > mx:
                raise GS1Error(f"AI ({ai}) value must be 1..{mx} characters")
            if ai in _NUM_ONLY and not val.isdigit():
                raise GS1Error(f"AI ({ai}) must be numeric")
            if any(ord(c) < 32 or ord(c) > 126 for c in val):
                raise GS1Error(f"AI ({ai}) has non-printable characters")
            parts.append(ai + val + (FNC1 if k < len(pairs) - 1 else ""))
        else:
            raise GS1Error(f"unsupported AI ({ai})")
        _interpret(ai, val)       # validates dates / check digits
    return FNC1 + "".join(parts)
