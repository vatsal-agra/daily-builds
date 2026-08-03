"""A minimal HTTP/1.0 request/response exchange running over MiniTCPSocket —
proof that Undertow is a general-purpose reliable substrate (any
request/response or streaming protocol can ride on it), not a file-copy-only
hack.

Deliberately tiny: just enough of HTTP/1.0 (request line, headers, a
Content-Length-terminated body) to serve real static content and get a real
parsed response back, through the same lossy network as everything else.
"""
import time

from .socket_ import MiniTCPSocket

CRLF = b"\r\n"


def _format_response(status_code, status_text, body, content_type="text/plain"):
    header = (
        f"HTTP/1.0 {status_code} {status_text}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("ascii")
    return header + body


def serve_one_request(local_addr, routes, event_log=None, name="httpd", timeout=30.0):
    """Accept exactly one connection, serve exactly one HTTP/1.0 request
    from `routes` (a dict of path -> bytes body), then close."""
    sock = MiniTCPSocket(local_addr, event_log=event_log, name=name)
    sock.listen()
    sock.accept(timeout=timeout)

    # A GET request has no body, so it's fully framed by the blank line
    # ending its headers — read incrementally until we see it, rather than
    # waiting for the client to close its side. (The client can't close
    # after sending the request: it still needs the connection open to
    # read the response. Undertow has no half-close/shutdown(SHUT_WR), so
    # relying on connection-close to frame the request would deadlock both
    # ends waiting on each other — caught by running this end-to-end.)
    deadline = time.monotonic() + timeout
    raw = b""
    while CRLF * 2 not in raw:
        remaining = max(0.0, deadline - time.monotonic())
        chunk = sock.recv(4096, timeout=remaining)
        if not chunk:
            break
        raw += chunk

    method = path = None
    try:
        request_line = raw.split(CRLF, 1)[0].decode("ascii")
        method, path, _version = request_line.split(" ")
    except (ValueError, UnicodeDecodeError):
        pass  # malformed or empty request — handled as 400 below, not silently treated as "GET /"

    if method is None:
        response = _format_response(400, "Bad Request", b"malformed or empty request line")
    elif method != "GET":
        response = _format_response(405, "Method Not Allowed", b"only GET is supported")
    elif path in routes:
        body = routes[path]
        content_type = "text/html" if path.endswith(".html") else "text/plain"
        response = _format_response(200, "OK", body, content_type)
    else:
        response = _format_response(404, "Not Found", f"no route for {path}".encode())

    sock.send(response)
    sock.close(timeout=timeout)
    return {"method": method, "path": path, "response_bytes": len(response)}


def fetch(local_addr, peer_addr, path="/", event_log=None, name="httpc", timeout=30.0):
    """Open a connection, send a GET request, return the parsed response."""
    sock = MiniTCPSocket(local_addr, event_log=event_log, name=name)
    t0 = time.monotonic()
    sock.connect(peer_addr, timeout=timeout)
    request = f"GET {path} HTTP/1.0\r\nHost: undertow.local\r\n\r\n".encode("ascii")
    sock.send(request)
    raw = sock.recv_all(timeout=timeout)
    sock.close(timeout=timeout)
    elapsed = time.monotonic() - t0

    header_blob, _, body = raw.partition(CRLF * 2)
    lines = header_blob.split(CRLF)
    status_line = lines[0].decode("ascii", errors="replace") if lines else ""
    parts = status_line.split(" ", 2)
    status_code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None

    headers = {}
    for line in lines[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.decode("ascii").strip().lower()] = v.decode("ascii").strip()

    return {
        "status_code": status_code,
        "status_line": status_line,
        "headers": headers,
        "body": body,
        "elapsed_seconds": elapsed,
    }
