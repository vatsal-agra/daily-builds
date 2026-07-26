"""
Runs a trained model over an input string and exports a JSON trace for
viz/visualizer.html: per-layer/per-head attention weights for that input,
plus a step-through autoregressive generation trace (top-8 next-token
probabilities at every step). No server involved — the visualizer loads
this file straight off disk via a file picker.
"""
import json

import numpy as np

from .generate import sample_from_logits
from .tensor_ops import softmax
from .tokenizer import EOT_ID


def export_trace(model, tokenizer, config, input_text, out_path, max_gen_steps=30, seed=0,
                  temperature=0.9, top_k=40, top_p=0.95):
    ids = tokenizer.encode(input_text)[: config.n_ctx]
    if not ids:
        ids = [EOT_ID]
    idx = np.array([ids], dtype=np.int64)

    model.forward(idx)  # populate attention caches for every block
    token_strs = [tokenizer.decode([i]) for i in ids]

    layers_data = []
    for li, block in enumerate(model.blocks):
        _, T, q, k, v, p, scale = block.attn._cache
        layers_data.append({"layer": li, "heads": p[0].tolist()})  # (n_head, T, T)

    rng = np.random.default_rng(seed)
    gen_idx = idx.copy()
    gen_steps = []
    for _ in range(max_gen_steps):
        window = gen_idx[:, -config.n_ctx:]
        logits = model.forward(window)
        last = logits[0, -1]
        probs = softmax(last[None, :])[0]
        top_ids = np.argsort(-probs)[:8]
        top = [[tokenizer.decode([int(t)]), float(probs[t])] for t in top_ids]
        next_id = int(sample_from_logits(last[None, :], temperature, top_k, top_p, rng)[0])
        chosen = tokenizer.decode([next_id])
        gen_steps.append({
            "prompt_so_far": tokenizer.decode(gen_idx[0].tolist()),
            "top": top,
            "chosen_display": "<EOT>" if next_id == EOT_ID else chosen,
        })
        gen_idx = np.concatenate([gen_idx, [[next_id]]], axis=1)
        if next_id == EOT_ID:
            break

    trace = {
        "input_text": input_text,
        "tokens": token_strs,
        "n_head": config.n_head,
        "n_layer": config.n_layer,
        "layers": layers_data,
        "generation": gen_steps,
        "final_text": tokenizer.decode([t for t in gen_idx[0].tolist() if t != EOT_ID]),
    }
    with open(out_path, "w") as f:
        json.dump(trace, f)
    return trace
