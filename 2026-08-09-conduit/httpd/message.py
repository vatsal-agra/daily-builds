"""HTTP/1.1 request/response value objects and status reason phrases."""

REASON_PHRASES = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    411: "Length Required",
    413: "Payload Too Large",
    414: "URI Too Long",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    501: "Not Implemented",
    505: "HTTP Version Not Supported",
}


class Request:
    def __init__(self, method, path, version, headers, body=b""):
        self.method = method
        self.path = path
        self.version = version
        self.headers = headers  # dict[str(lowercase), str]
        self.body = body

    def header(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def __repr__(self):
        return f"Request({self.method} {self.path} {self.version})"


class Response:
    def __init__(self, status=200, headers=None, body=b"", reason=None):
        self.status = status
        self.headers = dict(headers or {})
        self.body = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
        self.reason = reason or REASON_PHRASES.get(status, "Unknown")
