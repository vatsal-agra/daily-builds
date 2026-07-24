"""stdlib-only HTTP backend for the Loom web UI.

Loads a trained checkpoint once at startup and serves it over three JSON
endpoints (/api/generate, /api/attention, /api/status) plus the static
frontend. No model logic lives in the browser -- every generation and
attention request is a real forward pass through the loaded weights,
same server-does-the-work pattern as Formulate's spreadsheet engine.
"""
import argparse
import json
import math
import os
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import checkpoint as ckpt_mod
from .generate import generate_text, attention_weights

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(HERE, "static")

_STATE = {}


class BadRequest(ValueError):
    """Raised by request-parsing helpers; caught in do_POST and turned into
    a clean HTTP 400 instead of leaking a 500 for ordinary bad input (wrong
    JSON type, non-finite number, etc.)."""


def _numeric_field(payload, key, default, lo, hi, cast):
    val = payload.get(key, default)
    try:
        val = cast(val)
    except (TypeError, ValueError):
        raise BadRequest(f"{key!r} must be a {cast.__name__}, got {val!r}")
    if isinstance(val, float) and not math.isfinite(val):
        raise BadRequest(f"{key!r} must be finite, got {val!r}")
    return max(lo, min(val, hi))


def _load(ckpt_dir):
    model, tokenizer, meta = ckpt_mod.load(ckpt_dir)
    _STATE["model"] = model
    _STATE["tokenizer"] = tokenizer
    _STATE["meta"] = meta
    _STATE["ckpt_dir"] = ckpt_dir
    _STATE["loaded_at"] = time.time()


def _reload_if_changed():
    """Picks up a fresher checkpoint written by a still-running training
    job, so the UI's loss chart and generations improve live during
    training instead of needing a server restart."""
    ckpt_dir = _STATE["ckpt_dir"]
    meta_path = os.path.join(ckpt_dir, "meta.json")
    try:
        mtime = os.path.getmtime(meta_path)
    except OSError:
        return
    if mtime > _STATE.get("meta_mtime", 0):
        try:
            _load(ckpt_dir)
            _STATE["meta_mtime"] = mtime
        except Exception:
            pass  # a write-in-progress checkpoint may be briefly inconsistent; keep serving the old one


class Handler(BaseHTTPRequestHandler):
    server_version = "Loom/1.0"

    def log_message(self, fmt, *args):
        pass  # keep stdout clean; errors are still surfaced via _send_json

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
            elif path == "/app.js":
                self._send_file(os.path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8")
            elif path == "/style.css":
                self._send_file(os.path.join(STATIC_DIR, "style.css"), "text/css; charset=utf-8")
            elif path == "/api/status":
                _reload_if_changed()
                meta = _STATE["meta"]
                model = _STATE["model"]
                self._send_json({
                    "ok": True,
                    "vocab_size": model.cfg.vocab_size,
                    "block_size": model.cfg.block_size,
                    "n_layer": model.cfg.n_layer,
                    "n_head": model.cfg.n_head,
                    "n_embd": model.cfg.n_embd,
                    "num_params": model.num_params(),
                    "step": meta.get("step"),
                    "max_steps": meta.get("max_steps"),
                    "history": meta.get("history", []),
                    "baseline_loss": math.log(model.cfg.vocab_size),
                })
            else:
                self._send_json({"ok": False, "error": f"not found: {path}"}, status=404)
        except Exception as e:  # pragma: no cover - defensive; surfaced to client rather than crashing the server
            self._send_json({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "malformed JSON body"}, status=400)
                return

            if path == "/api/generate":
                self._handle_generate(payload)
            elif path == "/api/attention":
                self._handle_attention(payload)
            else:
                self._send_json({"ok": False, "error": f"not found: {path}"}, status=404)
        except BadRequest as e:
            self._send_json({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

    def _handle_generate(self, payload):
        _reload_if_changed()
        model, tokenizer = _STATE["model"], _STATE["tokenizer"]

        prompt = payload.get("prompt", "")
        if not isinstance(prompt, str):
            raise BadRequest("prompt must be a string")

        max_new_tokens = int(_numeric_field(payload, "max_new_tokens", 200, 1, 500, float))
        temperature = _numeric_field(payload, "temperature", 0.8, 0.0, 5.0, float)
        top_k = int(_numeric_field(payload, "top_k", 40, 0, model.cfg.vocab_size, float))
        top_p = _numeric_field(payload, "top_p", 0.0, 0.0, 1.0, float)
        seed_raw = payload.get("seed")
        seed = None
        if seed_raw is not None:
            seed = int(_numeric_field(payload, "seed", 0, -(2 ** 31), 2 ** 31 - 1, float))

        t0 = time.time()
        text = generate_text(model, tokenizer, prompt, max_new_tokens, temperature, top_k, top_p, seed)
        self._send_json({
            "ok": True,
            "prompt": prompt,
            "text": text,
            "elapsed_s": time.time() - t0,
        })

    def _handle_attention(self, payload):
        _reload_if_changed()
        model, tokenizer = _STATE["model"], _STATE["tokenizer"]
        prompt = payload.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            self._send_json({"ok": False, "error": "prompt must be a non-empty string"}, status=400)
            return

        full_ids = tokenizer.encode(prompt)
        ids = full_ids[:model.cfg.block_size]
        if not ids:
            self._send_json({"ok": False, "error": "prompt encoded to zero tokens"}, status=400)
            return
        tokens = [tokenizer.decode([i]) for i in ids]
        layers = attention_weights(model, ids)
        self._send_json({
            "ok": True,
            "tokens": tokens,
            "layers": [layer.tolist() for layer in layers],  # (n_head, T, T) per layer
            "truncated": len(full_ids) > len(ids),
        })


def main():
    ap = argparse.ArgumentParser(description="Serve the Loom web UI + API for a trained checkpoint.")
    ap.add_argument("--checkpoint", default=os.path.join(HERE, "checkpoints", "loom-shakespeare"))
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(args.checkpoint, "weights.npz")):
        raise SystemExit(
            f"no checkpoint found at {args.checkpoint} -- run `python -m loom.train` first, "
            f"or pass --checkpoint <dir>"
        )
    _load(args.checkpoint)
    _STATE["meta_mtime"] = os.path.getmtime(os.path.join(args.checkpoint, "meta.json"))
    print(f"loaded checkpoint from {args.checkpoint} (step {_STATE['meta'].get('step')})")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Loom serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
