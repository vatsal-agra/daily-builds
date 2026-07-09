"""Run a forward pass over a prompt, capture every layer's every head's
real post-softmax attention-weight matrix, and render a self-contained
interactive HTML visualizer (data embedded inline -- no fetch, no server,
works straight off `file://`)."""
import json
import os

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(os.path.dirname(_HERE), "viz", "attention_template.html")
PLACEHOLDER = "__LOOM_DATA_JSON__"


def trace(model, tokenizer, prompt):
    if not prompt:
        raise ValueError("prompt must be non-empty for attention tracing")
    prompt = prompt[: model.max_len]
    ids = tokenizer.encode(prompt)
    x = np.array([ids])
    model.forward(x)
    layers = model.attention_maps()  # list of (n_head, T, T)
    return {
        "tokens": list(prompt),
        "config": model.config(),
        "layers": [layer.tolist() for layer in layers],
    }


def render_html(data, template_path=None):
    template_path = template_path or TEMPLATE_PATH
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    if PLACEHOLDER not in template:
        raise ValueError(f"template {template_path!r} is missing the {PLACEHOLDER!r} placeholder")
    return template.replace(PLACEHOLDER, json.dumps(data))


def export(model, tokenizer, prompt, out_path, loss_history=None, template_path=None):
    data = trace(model, tokenizer, prompt)
    if loss_history:
        data["loss_history"] = loss_history
    html = render_html(data, template_path=template_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return data
