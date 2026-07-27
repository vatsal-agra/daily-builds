"""A stdlib-only `http.server` backend for the derivation-tree visualizer.

Zero client-side inference logic: the browser sends raw source text to
`/api/infer` and renders whatever JSON comes back. Every lex/parse/infer/
eval step happens here, in real Python, the same "server-backed browser
UI" pattern this repo has used before (Gambit's chess board, Formulate's
spreadsheet, Trove's search box).
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..lexer import LexError
from ..parser import parse, ParseError
from ..infer import infer_program, InferError
from ..evaluator import eval_expr, EvalError, format_value
from ..diagnostics import format_error_at, format_error_span
from ..types import pretty
from .templates import PAGE_HTML

sys.setrecursionlimit(max(sys.getrecursionlimit(), 100_000))

EXAMPLES = [
    {"name": "Let-polymorphism", "source": "let id = fun x -> x in (id 1, id true)"},
    {
        "name": "Factorial",
        "source": "let rec fact n = if n = 0 then 1 else n * fact (n - 1) in fact 10",
    },
    {"name": "Occurs-check failure", "source": "fun x -> x x"},
    {
        "name": "List map",
        "source": (
            "let rec map f l = match l with | [] -> [] | h :: t -> f h :: map f t "
            "in map (fun x -> x * 2) [1, 2, 3, 4]"
        ),
    },
    {
        "name": "Option lookup",
        "source": (
            "let rec assoc key l = match l with "
            "| [] -> None "
            "| (k, v) :: rest -> if k = key then Some v else assoc key rest "
            "in match assoc 2 [(1, 10), (2, 42)] with | Some v -> v | None -> 0"
        ),
    },
    {
        "name": "Type error",
        "source": "let f = fun n -> if n then n + 1 else 0 in f true",
    },
]


def serialize_judgment(j):
    return {
        "label": j.label,
        "type": pretty(j.ty),
        "note": j.note,
        "children": [serialize_judgment(c) for c in j.children],
    }


def run_inference(source):
    """Lex + parse + infer + evaluate `source`. Returns a JSON-safe dict."""
    try:
        expr = parse(source)
    except LexError as e:
        return {"ok": False, "error": format_error_at(source, e.message, e.line, e.col)}
    except ParseError as e:
        return {"ok": False, "error": format_error_at(source, e.message, e.line, e.col)}

    try:
        ty, judgment, _counter = infer_program(expr)
    except InferError as e:
        return {"ok": False, "error": format_error_span(source, e.message, e.span)}

    result = {"ok": True, "type": pretty(ty), "derivation": serialize_judgment(judgment)}

    try:
        value = eval_expr({}, expr)
        result["value"] = format_value(value)
    except EvalError as e:
        result["eval_error"] = format_error_span(source, e.message, e.span or expr.span)
    except RecursionError:
        result["eval_error"] = "error: recursion too deep (stack overflow)"
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "UnifyVisualizer/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the console quiet; errors still surface via HTTP status codes

    def _send(self, code, content_type, body):
        body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE_HTML)
        elif self.path == "/api/examples":
            self._send(200, "application/json", json.dumps(EXAMPLES))
        else:
            self._send(404, "text/plain; charset=utf-8", "not found")

    def do_POST(self):
        if self.path != "/api/infer":
            self._send(404, "text/plain; charset=utf-8", "not found")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            source = payload.get("source", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, "application/json", json.dumps({"ok": False, "error": "malformed request body"}))
            return
        self._send(200, "application/json", json.dumps(run_inference(source)))


def main(host="127.0.0.1", port=8765):
    server = HTTPServer((host, port), Handler)
    print(f"Unify visualizer running at http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
