"""A zero-dependency http.server playground for a trained Sprout checkpoint.

The browser holds no model logic at all -- every keystroke of "Generate"
does a real network round trip to this process, which runs the actual
Python forward pass. Same "server holds the real logic" pattern this repo's
Gambit and Formulate builds used for their browser UIs.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from generate import sample
from train import load_checkpoint

HERE = os.path.dirname(__file__)

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Sprout playground</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 760px; margin: 2rem auto; padding: 0 1rem;
    background: #0f1117; color: #e8e8ec;
  }
  h1 { font-size: 1.4rem; margin-bottom: 0.1rem; }
  .subtitle { color: #9aa0ac; font-size: 0.9rem; margin-bottom: 1.4rem; }
  textarea {
    width: 100%; box-sizing: border-box; min-height: 5rem; font-size: 1rem;
    font-family: ui-monospace, monospace; background: #1a1d27; color: #e8e8ec;
    border: 1px solid #333844; border-radius: 8px; padding: 0.7rem; resize: vertical;
  }
  .row { display: flex; gap: 1.2rem; margin: 0.9rem 0; flex-wrap: wrap; align-items: center; }
  .row label { font-size: 0.82rem; color: #9aa0ac; display: flex; gap: 0.4rem; align-items: center; }
  input[type=number] { width: 4.5rem; background: #1a1d27; color: #e8e8ec; border: 1px solid #333844; border-radius: 5px; padding: 0.25rem; }
  button {
    background: #6ea8fe; color: #0f1117; border: none; border-radius: 8px;
    padding: 0.6rem 1.3rem; font-weight: 600; cursor: pointer; font-size: 0.95rem;
  }
  button:disabled { opacity: 0.5; cursor: default; }
  #output {
    white-space: pre-wrap; font-family: ui-monospace, monospace; background: #1a1d27;
    border: 1px solid #333844; border-radius: 8px; padding: 1rem; margin-top: 1rem; min-height: 3rem;
  }
  .meta { font-size: 0.78rem; color: #666; margin-top: 0.6rem; }
</style>
</head>
<body>
<h1>Sprout playground</h1>
<div class="subtitle">A ~1M-parameter transformer, trained from scratch on an original 170KB corpus. Type a prompt and generate a real completion.</div>
<textarea id="prompt" placeholder="the fox and the otter">the fox</textarea>
<div class="row">
  <label>Tokens <input type="number" id="maxTokens" value="80" min="1" max="500"></label>
  <label>Temperature <input type="number" id="temperature" value="0.8" step="0.1" min="0" max="2"></label>
  <label>Top-k <input type="number" id="topK" value="40" min="0" max="512"></label>
  <button id="go">Generate</button>
</div>
<div id="output">(output will appear here)</div>
<div class="meta" id="modelMeta"></div>
<script>
async function refreshMeta() {
  const r = await fetch('/meta');
  const j = await r.json();
  document.getElementById('modelMeta').textContent =
    `checkpoint step ${j.step} · ${j.num_params.toLocaleString()} params · vocab ${j.vocab_size} · block_size ${j.block_size}`;
}
refreshMeta();

document.getElementById('go').addEventListener('click', async () => {
  const btn = document.getElementById('go');
  const out = document.getElementById('output');
  btn.disabled = true;
  out.textContent = 'generating...';
  const body = {
    prompt: document.getElementById('prompt').value,
    max_new_tokens: parseInt(document.getElementById('maxTokens').value) || 80,
    temperature: parseFloat(document.getElementById('temperature').value),
    top_k: parseInt(document.getElementById('topK').value) || null,
  };
  try {
    const r = await fetch('/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const j = await r.json();
    if (j.error) { out.textContent = 'Error: ' + j.error; }
    else { out.textContent = j.text; }
  } catch (e) {
    out.textContent = 'Request failed: ' + e;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    model = None
    tok = None
    ckpt_data = None

    def log_message(self, fmt, *args):
        pass  # keep stdout clean; nothing sensitive to hide, just quieter demo output

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/meta":
            self._send_json(
                {
                    "step": self.ckpt_data["step"],
                    "num_params": self.model.num_params(),
                    "vocab_size": self.model.vocab_size,
                    "block_size": self.model.block_size,
                }
            )
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        if self.path != "/generate":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            prompt = str(payload.get("prompt", "") or "")
            max_new_tokens = int(payload.get("max_new_tokens", 80) or 80)
            max_new_tokens = max(1, min(max_new_tokens, 500))
            temperature = float(payload.get("temperature", 0.8))
            top_k = payload.get("top_k", 40)
            top_k = int(top_k) if top_k else None

            # a fresh Generator per request avoids sharing mutable RNG state
            # across the threads ThreadingHTTPServer spawns per connection
            request_rng = np.random.default_rng()
            text = sample(
                self.model, self.tok, prompt=prompt, max_new_tokens=max_new_tokens,
                temperature=temperature, top_k=top_k, rng=request_rng,
            )
            self._send_json({"text": text})
        except Exception as e:  # a malformed request must not crash the server
            self._send_json({"error": str(e)}, status=400)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=os.path.join(HERE, "checkpoints", "sprout.pkl"))
    ap.add_argument("--port", type=int, default=8420)
    args = ap.parse_args()

    try:
        model, tok, data = load_checkpoint(args.checkpoint)
    except FileNotFoundError:
        raise SystemExit(f"No checkpoint found at {args.checkpoint}. Run train.py first.")

    Handler.model, Handler.tok, Handler.ckpt_data = model, tok, data

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Sprout playground running at http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
