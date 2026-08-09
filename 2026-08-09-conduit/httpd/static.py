"""A small static-file request handler for HttpServer — path-traversal
safe, with a minimal MIME-type table and directory index listing."""

import html
import os
import urllib.parse

from httpd.message import Response

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class StaticFileHandler:
    def __init__(self, root_dir):
        self.root = os.path.realpath(root_dir)

    def _resolve(self, url_path):
        decoded = urllib.parse.unquote(url_path.split("?", 1)[0])
        # Collapse to a path relative to root; realpath + prefix check
        # blocks `..` traversal regardless of how it's encoded.
        candidate = os.path.realpath(os.path.join(self.root, decoded.lstrip("/")))
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            return None
        return candidate

    def __call__(self, req):
        if req.method not in ("GET", "HEAD"):
            return Response(405, headers={"Allow": "GET, HEAD"}, body=b"Method Not Allowed")

        path = self._resolve(req.path)
        if path is None:
            return Response(403, body=b"Forbidden")
        if not os.path.exists(path):
            return Response(404, body=b"404 Not Found")

        if os.path.isdir(path):
            index = os.path.join(path, "index.html")
            if os.path.isfile(index):
                path = index
            else:
                return self._directory_listing(path, req.path)

        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return Response(403, body=b"Forbidden")

        ext = os.path.splitext(path)[1].lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")
        return Response(200, headers={"Content-Type": content_type}, body=body)

    def _directory_listing(self, dir_path, url_path):
        entries = sorted(os.listdir(dir_path))
        prefix = url_path if url_path.endswith("/") else url_path + "/"
        rows = "".join(
            f'<li><a href="{html.escape(prefix + e)}">{html.escape(e)}</a></li>' for e in entries
        )
        body = (
            f"<!doctype html><meta charset='utf-8'><title>Index of {html.escape(url_path)}</title>"
            f"<h1>Index of {html.escape(url_path)}</h1><ul>{rows}</ul>"
        ).encode("utf-8")
        return Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, body=body)
