"""Run a forward pass over a prompt and export every layer's every head's
real post-softmax attention-weight matrix, for the interactive visualizer."""
import json

import numpy as np


def trace(model, tokenizer, prompt):
    prompt = prompt[: model.max_len]
    if not prompt:
        raise ValueError("prompt must be non-empty for attention tracing")
    ids = tokenizer.encode(prompt)
    x = np.array([ids])
    model.forward(x)
    layers = model.attention_maps()  # list of (n_head, T, T)
    return {
        "tokens": list(prompt),
        "config": model.config(),
        "layers": [layer.tolist() for layer in layers],
    }


def export(model, tokenizer, prompt, path, loss_history=None):
    data = trace(model, tokenizer, prompt)
    if loss_history is not None:
        data["loss_history"] = loss_history
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
