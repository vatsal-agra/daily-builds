"""Checkpoint save/load: model weights + tokenizer merges + architecture config.

Hand-rolled binary weight storage via numpy's .npz (a zip of raw arrays,
which is a documented, simple format -- not a pickle, so loading a
checkpoint never executes arbitrary code) plus a JSON sidecar for
everything else.
"""

import json

import numpy as np

from .nn import LoomModel
from .tokenizer import BPETokenizer


def save_checkpoint(path, model, tokenizer, config, extra=None):
    params = model.parameters()
    arrays = {f"p{i}": p.data for i, p in enumerate(params)}
    np.savez(path + ".npz", **arrays)
    meta = {
        "config": config,
        "merges": [list(pair) for pair in tokenizer.merges_list],
        "extra": extra or {},
    }
    with open(path + ".json", "w") as f:
        json.dump(meta, f)


def load_checkpoint(path):
    with open(path + ".json") as f:
        meta = json.load(f)
    config = meta["config"]

    tokenizer = BPETokenizer()
    for a, b in meta["merges"]:
        new_id = 256 + len(tokenizer.merges_list)
        tokenizer.merges_list.append((a, b))
        tokenizer.merges[(a, b)] = new_id
        tokenizer.vocab[new_id] = tokenizer.vocab[a] + tokenizer.vocab[b]

    model = LoomModel(**config)
    data = np.load(path + ".npz")
    params = model.parameters()
    assert len(params) == len(data.files), (
        f"checkpoint has {len(data.files)} arrays but the reconstructed model "
        f"has {len(params)} parameters -- config mismatch"
    )
    for i, p in enumerate(params):
        arr = data[f"p{i}"]
        assert arr.shape == p.data.shape, f"param {i} shape mismatch: {arr.shape} vs {p.data.shape}"
        p.data = arr.astype(np.float64)
        p.grad = np.zeros_like(p.data)

    return model, tokenizer, config, meta.get("extra", {})
