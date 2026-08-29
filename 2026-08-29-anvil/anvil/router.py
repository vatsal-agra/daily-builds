"""Routing: exact and `{param}` path patterns, plus static file serving
with the parts a toy server usually skips -- ETag/Last-Modified conditional
GET and byte-range requests.
"""

import os
import re

from .http_message import Response
from .util import format_http_date, guess_mime, parse_http_date


def compile_pattern(pattern: str):
    """'/users/{id}/posts/{post_id}' -> (compiled regex, ['id', 'post_id'])"""
    parts = pattern.split("/")
    regex_parts = []
    names = []
    for part in parts:
        if part.startswith("{") and part.endswith("}") and len(part) > 2:
            name = part[1:-1]
            names.append(name)
            regex_parts.append(f"(?P<{name}>[^/]+)")
        else:
            regex_parts.append(re.escape(part))
    regex = re.compile("^" + "/".join(regex_parts) + "$")
    return regex, names


class Router:
    def __init__(self):
        self._routes = []       # [(method, regex, handler)]
        self._ws_routes = []    # [(regex, factory)]
        self._static_mounts = []  # [(prefix, directory)]

    def add_route(self, method, pattern, handler):
        regex, _ = compile_pattern(pattern)
        self._routes.append((method.upper(), regex, handler))
        return handler

    def route(self, method, pattern):
        def deco(fn):
            self.add_route(method, pattern, fn)
            return fn
        return deco

    def add_ws_route(self, pattern, factory):
        regex, _ = compile_pattern(pattern)
        self._ws_routes.append((regex, factory))
        return factory

    def mount_static(self, url_prefix, directory, index="index.html"):
        prefix = "/" + url_prefix.strip("/")
        self._static_mounts.append((prefix, os.path.abspath(directory), index))

    def match(self, method, path):
        """Returns (handler, params, allowed_methods_if_405) """
        allowed = set()
        for m, regex, handler in self._routes:
            mo = regex.match(path)
            if mo:
                if m == method or (method == "HEAD" and m == "GET"):
                    return handler, mo.groupdict(), None
                allowed.add(m)
        for prefix, directory, index in self._static_mounts:
            if path == prefix or path.startswith(prefix + "/"):
                if method not in ("GET", "HEAD"):
                    allowed.add("GET")
                    allowed.add("HEAD")
                    continue
                rel = path[len(prefix):].lstrip("/")
                return (
                    lambda req, rel=rel, directory=directory, index=index:
                        serve_static(req, directory, rel, index),
                    {},
                    None,
                )
        if allowed:
            return None, None, allowed
        return None, None, None

    def match_ws(self, path):
        for regex, factory in self._ws_routes:
            mo = regex.match(path)
            if mo:
                return factory, mo.groupdict()
        return None, None


class HttpError(Exception):
    def __init__(self, status, message=None, headers=None):
        super().__init__(message or "")
        self.status = status
        self.message = message
        self.headers = headers or []


def parse_range(header: str, size: int):
    """Parse a single-range 'Range: bytes=...' header. Multi-range
    requests are intentionally not supported (RFC 7233 allows a server to
    ignore Range entirely and return 200); we signal that by raising
    NotImplementedError so the caller falls back to a full 200 response,
    which is spec-legal."""
    if not header.startswith("bytes="):
        raise ValueError("unsupported range unit")
    spec = header[len("bytes="):].strip()
    if "," in spec:
        raise NotImplementedError("multi-range not supported")
    if "-" not in spec:
        raise ValueError("malformed range")
    start_s, _, end_s = spec.partition("-")
    if start_s == "":
        if end_s == "":
            raise ValueError("empty range")
        suffix = int(end_s)
        if suffix <= 0:
            raise ValueError("non-positive suffix length")
        if size == 0:
            raise ValueError("empty resource")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s != "" else size - 1
        if start < 0 or start > end:
            raise ValueError("malformed range bounds")
        if start >= size:
            raise ValueError("range start beyond resource size")
        end = min(end, size - 1)
    return start, end


def serve_static(req, directory, rel_path, index="index.html"):
    rel_path = rel_path or index
    # Path-traversal guard #1: reject ".." segments lexically before ever
    # touching the filesystem.
    full = os.path.normpath(os.path.join(directory, rel_path))
    if full != directory and not full.startswith(directory + os.sep):
        return Response.text("Forbidden", status=403)
    if os.path.isdir(full):
        full = os.path.join(full, index)
    if not os.path.isfile(full):
        return Response.text("Not Found", status=404)
    # Path-traversal guard #2: a symlink *inside* the mount can point
    # anywhere on disk and would sail straight past guard #1 (which only
    # inspects the request path, not what it resolves to) -- resolve and
    # re-check before ever opening the file.
    real_directory = os.path.realpath(directory)
    real_full = os.path.realpath(full)
    if real_full != real_directory and not real_full.startswith(real_directory + os.sep):
        return Response.text("Forbidden", status=403)

    stat = os.stat(full)
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    last_modified = format_http_date(stat.st_mtime)
    mime = guess_mime(full)

    inm = req.header("If-None-Match")
    ims = req.header("If-Modified-Since")
    not_modified = False
    if inm is not None:
        candidates = [t.strip() for t in inm.split(",")]
        not_modified = etag in candidates or "*" in candidates
    elif ims is not None:
        ims_epoch = parse_http_date(ims)
        if ims_epoch is not None and int(stat.st_mtime) <= ims_epoch:
            not_modified = True
    if not_modified:
        return Response(304, headers=[("ETag", etag), ("Last-Modified", last_modified)])

    file_size = stat.st_size
    base_headers = [
        ("Content-Type", mime),
        ("Accept-Ranges", "bytes"),
        ("ETag", etag),
        ("Last-Modified", last_modified),
    ]

    range_header = req.header("Range")
    if range_header:
        try:
            start, end = parse_range(range_header, file_size)
        except NotImplementedError:
            range_header = None  # fall through to a full 200 response
        except ValueError:
            return Response(
                416, headers=base_headers + [("Content-Range", f"bytes */{file_size}")],
            )
        else:
            range_len = end - start + 1
            headers = base_headers + [
                ("Content-Range", f"bytes {start}-{end}/{file_size}"),
                ("Content-Length", str(range_len)),
            ]
            if req.method == "HEAD":
                return Response(206, headers=headers, body=b"")
            with open(full, "rb") as f:
                f.seek(start)
                data = f.read(range_len)
            return Response(206, headers=headers, body=data)

    if req.method == "HEAD":
        headers = base_headers + [("Content-Length", str(file_size))]
        return Response(200, headers=headers, body=b"")
    with open(full, "rb") as f:
        data = f.read()
    return Response(200, headers=base_headers, body=data)
