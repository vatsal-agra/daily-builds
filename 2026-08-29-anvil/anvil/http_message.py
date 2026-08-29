"""Request/Response value objects and a case-insensitive, order-preserving
header container. This module has no socket code in it at all -- it's pure
data plus the wire-format serialization for a Response.
"""

from .util import parse_query, unquote

REASON_PHRASES = {
    100: "Continue", 101: "Switching Protocols",
    200: "OK", 201: "Created", 204: "No Content", 206: "Partial Content",
    301: "Moved Permanently", 302: "Found", 304: "Not Modified",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 408: "Request Timeout",
    411: "Length Required", 413: "Payload Too Large",
    414: "URI Too Long", 416: "Range Not Satisfiable",
    426: "Upgrade Required", 431: "Request Header Fields Too Large",
    500: "Internal Server Error", 501: "Not Implemented",
    502: "Bad Gateway", 503: "Service Unavailable",
}


class HeaderDict:
    """Case-insensitive, order-preserving, multi-value header container.
    Small header counts (a handful to a few dozen) mean linear scans are
    fine -- no need for a real hash index here."""

    __slots__ = ("_pairs",)

    def __init__(self, pairs=None):
        self._pairs = [(k, v) for k, v in pairs] if pairs else []

    def get(self, name, default=None):
        name_l = name.lower()
        for k, v in self._pairs:
            if k.lower() == name_l:
                return v
        return default

    def get_all(self, name):
        name_l = name.lower()
        return [v for k, v in self._pairs if k.lower() == name_l]

    def set(self, name, value):
        """Replace all existing occurrences of `name` with a single value."""
        name_l = name.lower()
        self._pairs = [(k, v) for k, v in self._pairs if k.lower() != name_l]
        self._pairs.append((name, str(value)))

    def add(self, name, value):
        """Append without removing existing occurrences (e.g. Set-Cookie)."""
        self._pairs.append((name, str(value)))

    def remove(self, name):
        name_l = name.lower()
        self._pairs = [(k, v) for k, v in self._pairs if k.lower() != name_l]

    def items(self):
        return list(self._pairs)

    def __contains__(self, name):
        return self.get(name) is not None

    def __iter__(self):
        return iter(self._pairs)

    def __len__(self):
        return len(self._pairs)

    def __repr__(self):
        return f"HeaderDict({self._pairs!r})"


class Request:
    __slots__ = (
        "method", "target", "version", "headers", "body", "trailers",
        "path", "query", "params",
    )

    def __init__(self, method, target, version, headers, body, trailers=None):
        self.method = method
        self.target = target
        self.version = version
        self.headers = headers
        self.body = body
        self.trailers = trailers if trailers is not None else HeaderDict()
        if "?" in target:
            raw_path, _, qs = target.partition("?")
        else:
            raw_path, qs = target, ""
        self.path = unquote(raw_path) if raw_path else "/"
        self.query = parse_query(qs)
        self.params = {}  # filled in by the router on a match

    def header(self, name, default=None):
        return self.headers.get(name, default)

    def json(self):
        import json
        return json.loads(self.body.decode("utf-8"))

    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def __repr__(self):
        return f"Request({self.method!r}, {self.target!r})"


class Response:
    __slots__ = ("status", "reason", "headers", "body")

    def __init__(self, status=200, headers=None, body=b"", reason=None):
        self.status = status
        self.reason = reason if reason is not None else REASON_PHRASES.get(status, "Unknown")
        self.headers = headers if isinstance(headers, HeaderDict) else HeaderDict(headers)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body

    @classmethod
    def json(cls, obj, status=200, headers=None):
        import json
        payload = json.dumps(obj).encode("utf-8")
        h = HeaderDict(headers)
        h.set("Content-Type", "application/json; charset=utf-8")
        return cls(status, h, payload)

    @classmethod
    def text(cls, s, status=200, headers=None):
        h = HeaderDict(headers)
        if h.get("Content-Type") is None:
            h.set("Content-Type", "text/plain; charset=utf-8")
        return cls(status, h, s)

    def to_bytes(self, version="HTTP/1.1", include_body=True):
        headers = HeaderDict(self.headers.items())
        if headers.get("Content-Length") is None and headers.get("Transfer-Encoding") is None:
            headers.set("Content-Length", str(len(self.body)))
        if headers.get("Date") is None:
            from .util import format_http_date
            import time
            headers.set("Date", format_http_date(time.time()))
        lines = [f"{version} {self.status} {self.reason}\r\n"]
        for k, v in headers.items():
            lines.append(f"{k}: {v}\r\n")
        lines.append("\r\n")
        head = "".join(lines).encode("latin-1")
        return head + (self.body if include_body else b"")

    def __repr__(self):
        return f"Response({self.status} {self.reason}, {len(self.body)} bytes)"
