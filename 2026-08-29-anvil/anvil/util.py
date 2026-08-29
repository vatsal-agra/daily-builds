"""Small hand-rolled helpers: percent-decoding, query parsing, HTTP dates,
and a tiny MIME table. None of these are "the protocol" (that's the parser
and the WebSocket codec) -- they're the boring plumbing every server needs,
kept dependency-free and easy to read.
"""

import calendar
import time

_HEXDIG = "0123456789abcdefABCDEF"


def unquote(s: str) -> str:
    """Percent-decode a URL component (hand-rolled, not urllib.parse)."""
    raw = s.encode("latin-1")
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == 0x25 and i + 2 < n and chr(raw[i + 1]) in _HEXDIG and chr(raw[i + 2]) in _HEXDIG:
            out.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(c)
            i += 1
    return out.decode("utf-8", errors="replace")


def parse_query(qs: str) -> dict:
    """'a=1&b=2&b=3' -> {'a': ['1'], 'b': ['2', '3']}"""
    result = {}
    if not qs:
        return result
    for part in qs.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        k = unquote(k.replace("+", " "))
        v = unquote(v.replace("+", " "))
        result.setdefault(k, []).append(v)
    return result


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def format_http_date(epoch_seconds: float) -> str:
    """RFC 7231 IMF-fixdate, e.g. 'Sun, 06 Nov 1994 08:49:37 GMT'."""
    t = time.gmtime(epoch_seconds)
    return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (
        _WEEKDAYS[t.tm_wday], t.tm_mday, _MONTHS[t.tm_mon - 1], t.tm_year,
        t.tm_hour, t.tm_min, t.tm_sec,
    )


def parse_http_date(s: str):
    """Parse the three legal RFC 7231 date formats. Returns epoch seconds
    (int) or None if unparseable -- callers must treat that as 'no match'
    rather than an error, per spec."""
    s = s.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S GMT",   # IMF-fixdate (preferred)
        "%A, %d-%b-%y %H:%M:%S GMT",   # obsolete RFC 850
        "%a %b %d %H:%M:%S %Y",        # asctime()
    ):
        try:
            tm = time.strptime(s, fmt)
            return calendar.timegm(tm)
        except ValueError:
            continue
    return None


_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".wasm": "application/wasm",
    ".pdf": "application/pdf",
    ".xml": "application/xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".bin": "application/octet-stream",
}


def guess_mime(path: str) -> str:
    lower = path.lower()
    for ext, mime in _MIME_TYPES.items():
        if lower.endswith(ext):
            return mime
    return "application/octet-stream"
