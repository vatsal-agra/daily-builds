"""stdlib-only HTTP server: JSON search API + the static single-page UI."""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .query import search as run_search
from .snippet import make_snippet, to_html

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _read_source_snippet(index, path, matched_terms):
    full_path = os.path.join(index.root, path)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return to_html(make_snippet(f.read(), matched_terms))
    except OSError:
        return "<em>(source file unavailable)</em>"


def make_handler(index):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Glean/1.0"

        def log_message(self, fmt, *args):
            pass  # keep stdout clean; errors still surface via exceptions

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, rel_path, content_type):
            full_path = os.path.join(STATIC_DIR, rel_path)
            try:
                with open(full_path, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_json({"error": "not found"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path in ("/", "/index.html"):
                self._send_file("index.html", "text/html; charset=utf-8")
                return

            if parsed.path == "/api/stats":
                self._send_json(
                    {
                        "root": index.root,
                        "documents": index.doc_count,
                        "vocabulary": len(index.terms),
                        "avg_doc_length": round(index.avg_doc_length, 1),
                    }
                )
                return

            if parsed.path == "/api/search":
                query = (params.get("q") or [""])[0].strip()
                if not query:
                    self._send_json({"results": [], "suggestions": [], "error": None})
                    return
                try:
                    limit = int((params.get("limit") or ["10"])[0])
                except ValueError:
                    limit = 10
                limit = max(1, min(limit, 50))
                try:
                    results, suggestions, matched_terms = run_search(index, query, limit=limit)
                except Exception as exc:  # query parsing is user input -> never 500 the server
                    self._send_json({"results": [], "suggestions": [], "error": str(exc)}, status=400)
                    return
                for r in results:
                    r["snippet"] = _read_source_snippet(index, r["path"], matched_terms)
                self._send_json({"results": results, "suggestions": suggestions, "error": None})
                return

            self._send_json({"error": "not found"}, status=404)

    return Handler


def serve(index, port=8899, bind="127.0.0.1"):
    handler = make_handler(index)
    try:
        httpd = ThreadingHTTPServer((bind, port), handler)
    except OSError as exc:
        print(f"error: could not bind {bind}:{port} -- {exc}", file=sys.stderr)
        print("try a different --port", file=sys.stderr)
        sys.exit(1)
    print(f"Glean serving {index.doc_count} document(s) from {index.root}")
    print(f"  -> http://{bind}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
