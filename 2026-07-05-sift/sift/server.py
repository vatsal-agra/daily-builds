"""A minimal stdlib http.server backend for the interactive search UI.
Serves a JSON search API backed by the real Python ranking engine (no
mocked/stubbed responses) and the self-contained static/index.html file."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep demo/test output quiet

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                self._serve_static("index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/api/search":
                self._handle_search(parse_qs(parsed.query))
                return
            if parsed.path == "/api/stats":
                self._send_json(
                    {
                        "doc_count": engine.index.doc_count,
                        "vocab_size": len(engine.index.vocabulary()),
                        "avg_doc_length": round(engine.index.avg_doc_length, 2),
                    }
                )
                return
            self.send_error(404, "not found")

        def _serve_static(self, filename, content_type):
            path = os.path.join(_STATIC_DIR, filename)
            try:
                with open(path, "rb") as fh:
                    body = fh.read()
            except FileNotFoundError:
                self.send_error(404, "not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_search(self, params):
            query = (params.get("q") or [""])[0].strip()
            limit = int((params.get("limit") or ["10"])[0])
            if not query:
                self._send_json({"query": "", "results": [], "elapsed_ms": 0, "suggestions": []})
                return

            t0 = time.time()
            try:
                results = engine.search(query, limit=limit)
                error = None
            except Exception as exc:
                results = []
                error = str(exc)
            elapsed_ms = round((time.time() - t0) * 1000, 2)

            payload_results = []
            for doc_id, score in results:
                doc = engine.index.documents[doc_id]
                snippet = engine.snippet_for(doc_id, query)
                payload_results.append(
                    {
                        "doc_id": doc_id,
                        "title": doc.title,
                        "path": doc.path,
                        "score": round(score, 4),
                        "snippet_html": snippet,
                    }
                )

            suggestions = []
            if not payload_results and error is None:
                from sift.analyzer import analyze_query_term

                seen = set()
                for word in query.split():
                    cleaned = word.strip('"()*~')
                    if not cleaned or cleaned.lower() in ("and", "or", "not"):
                        continue
                    for w, _ in engine.suggest(analyze_query_term(cleaned)):
                        if w not in seen:
                            seen.add(w)
                            suggestions.append(w)

            self._send_json(
                {
                    "query": query,
                    "results": payload_results,
                    "elapsed_ms": elapsed_ms,
                    "suggestions": suggestions[:5],
                    "error": error,
                }
            )

    return Handler


def run_server(engine, port=8000):
    handler = make_handler(engine)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Sift serving {engine.index.doc_count} documents at http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
