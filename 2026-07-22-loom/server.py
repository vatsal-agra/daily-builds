#!/usr/bin/env python3
"""Loom playground server.

Serves a static HTML/JS UI and a JSON API backed by the real trained Python
model -- the browser holds zero model logic, every generation request is a
network round trip to this process, exactly like Gambit's chess board and
Formulate's spreadsheet engine in this same repo. Uses only the Python
standard library (http.server), no web framework.
"""

import argparse
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from loom.checkpoint import load_checkpoint
from loom.generate import generate, attention_snapshot

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

STATE = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout quiet; the CLI already prints what matters

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_file(os.path.join(STATIC_DIR, "playground.html"), "text/html; charset=utf-8")
        elif parsed.path == "/api/info":
            model, tokenizer = STATE["model"], STATE["tokenizer"]
            self._send_json({
                "vocab_size": model.vocab_size,
                "dim": model.dim,
                "n_layers": len(model.blocks),
                "n_heads": model.blocks[0].attn.n_heads,
                "max_seq_len": model.max_seq_len,
                "num_params": model.num_params(),
                "checkpoint": STATE["checkpoint_path"],
                "extra": STATE.get("extra", {}),
                "train_log": STATE.get("train_log"),
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON body"}, status=400)
            return

        if parsed.path == "/api/generate":
            self._handle_generate(payload)
        elif parsed.path == "/api/attention":
            self._handle_attention(payload)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_generate(self, payload):
        model, tokenizer = STATE["model"], STATE["tokenizer"]
        prompt = str(payload.get("prompt", ""))[:500]
        max_new_tokens = int(payload.get("max_new_tokens", 120))
        max_new_tokens = max(1, min(max_new_tokens, model.max_seq_len))
        temperature = float(payload.get("temperature", 0.8))
        temperature = max(0.05, min(temperature, 3.0))
        top_k = payload.get("top_k")
        top_k = int(top_k) if top_k not in (None, "", 0) else None
        top_p = payload.get("top_p")
        top_p = float(top_p) if top_p not in (None, "") else None
        seed = payload.get("seed")
        rng = np.random.default_rng(int(seed)) if seed not in (None, "") else np.random.default_rng()

        t0 = time.time()
        try:
            text, ids = generate(model, tokenizer, prompt, max_new_tokens,
                                  temperature=temperature, top_k=top_k, top_p=top_p,
                                  rng=rng, use_cache=True)
        except Exception as e:
            self._send_json({"error": str(e)}, status=400)
            return
        elapsed = time.time() - t0
        self._send_json({
            "prompt": prompt,
            "text": text,
            "num_tokens": len(ids),
            "elapsed_sec": round(elapsed, 3),
        })

    def _handle_attention(self, payload):
        model, tokenizer = STATE["model"], STATE["tokenizer"]
        text = str(payload.get("text", ""))[:2000]
        if not text:
            self._send_json({"error": "text must be non-empty"}, status=400)
            return
        try:
            tokens, layers = attention_snapshot(model, tokenizer, text)
        except Exception as e:
            self._send_json({"error": str(e)}, status=400)
            return
        self._send_json({
            "tokens": tokens,
            "layers": [layer.tolist() for layer in layers],  # each: (n_heads, T, T)
        })


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", default="checkpoints/loom")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    print(f"Loading checkpoint {args.checkpoint} ...")
    model, tokenizer, config, extra = load_checkpoint(args.checkpoint)
    STATE["model"] = model
    STATE["tokenizer"] = tokenizer
    STATE["checkpoint_path"] = args.checkpoint
    STATE["extra"] = extra
    log_path = os.path.join(os.path.dirname(args.checkpoint) or ".", "train_log.json")
    if os.path.exists(log_path):
        with open(log_path) as f:
            STATE["train_log"] = json.load(f).get("log")

    print(f"Model: {model.num_params():,} params, vocab {model.vocab_size}, "
          f"{len(model.blocks)} layers x {model.blocks[0].attn.n_heads} heads")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Loom playground running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
