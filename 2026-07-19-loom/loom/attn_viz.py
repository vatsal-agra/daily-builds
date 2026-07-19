"""Renders viz/attention.html: an interactive, self-contained visualizer
for a real generation run, embedding the actual per-layer/per-head
attention-weight matrices captured during sampling as JSON."""
import json
import os

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "viz", "attention_template.html")


def render(frames, text, out_path):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    payload = json.dumps({"text": text, "frames": frames})
    # Generated text is arbitrary model output; if it ever contains "</script>"
    # (e.g. a corpus retrained on HTML-ish text), an unescaped "</" would
    # close the embedding <script> block early and break out of the JSON
    # literal into the surrounding page markup.
    payload = payload.replace("</", "<\\/")
    html = template.replace("__LOOM_DATA__", payload)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
