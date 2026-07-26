"""A stdlib http.server JSON API backing the browser search UI. All parsing
and ranking logic stays server-side — the page holds zero search logic of
its own, only rendering."""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import rank
from .engine import SearchEngine
from .query import QuerySyntaxError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class Handler(BaseHTTPRequestHandler):
    engine = None  # set by run_server before serve_forever()

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            self._send_html((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path == "/api/search":
            self._handle_search(params)
        elif path == "/api/autocomplete":
            self._handle_autocomplete(params)
        elif path == "/api/stats":
            self._send_json(self.engine.stats())
        else:
            self._send_json({"error": "not found"}, status=404)

    def _handle_search(self, params):
        q = (params.get("q") or [""])[0]
        try:
            top_k = max(0, min(50, int((params.get("k") or ["10"])[0])))
        except ValueError:
            top_k = 10

        if not q.strip():
            self._send_json({"results": [], "suggestions": {}, "query": q})
            return

        try:
            results = self.engine.search(q, top_k=top_k)
        except QuerySyntaxError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        payload_results = [
            {
                "title": r.title,
                "path": r.path,
                "score": round(r.score, 4),
                "snippet_html": rank.snippet_to_html(r.snippet_pieces),
            }
            for r in results
        ]
        suggestions = {}
        if not payload_results:
            raw = self.engine.did_you_mean(q)
            suggestions = {term: [w for w, _d in cands] for term, cands in raw.items()}
        self._send_json({"results": payload_results, "suggestions": suggestions, "query": q})

    def _handle_autocomplete(self, params):
        q = (params.get("q") or [""])[0]
        completions = self.engine.autocomplete(q, limit=8)
        self._send_json({"completions": completions})


def _load_engine(index_path, demo):
    if demo:
        from corpus.demo_corpus import load_corpus

        engine = SearchEngine()
        for article in load_corpus():
            engine.add_document(article["title"], article["text"], path=article["topic"])
        engine.save(index_path)
        return engine

    if not Path(index_path).exists():
        print(
            f"error: index file not found: {index_path!r} (run `glean index` first, or pass --demo)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return SearchEngine.load(index_path)
    except Exception as exc:  # corrupt/foreign index file
        print(f"error: could not load index {index_path!r}: {exc}", file=sys.stderr)
        sys.exit(1)


def run_server(index_path, port, demo=False):
    engine = _load_engine(index_path, demo)
    Handler.engine = engine
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Glean serving {engine.stats()['documents']} documents at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
