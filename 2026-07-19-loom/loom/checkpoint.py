"""Checkpoint save/load. Model params() returns a flat list of Tensors in a
deterministic construction order, so weights round-trip by position."""
import json
import os
import numpy as np
from .nn import GPT
from .tokenizer import tokenizer_from_dict


def save_checkpoint(path, model, tokenizer, config):
    out_dir = os.path.dirname(os.path.abspath(str(path)))
    os.makedirs(out_dir, exist_ok=True)
    params = model.params()
    arrays = {f"w{i}": p.data for i, p in enumerate(params)}
    np.savez(path, **arrays)
    meta_path = str(path) + ".json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"config": config, "tokenizer": tokenizer.to_dict()}, f)


def load_checkpoint(path):
    meta_path = str(path) + ".json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    config = meta["config"]
    tokenizer = tokenizer_from_dict(meta["tokenizer"])
    model = GPT(
        vocab_size=config["vocab_size"],
        d_model=config["d_model"],
        n_heads=config["n_heads"],
        n_layers=config["n_layers"],
        d_ff=config["d_ff"],
        max_seq_len=config["max_seq_len"],
    )
    npz_path = path if str(path).endswith(".npz") else str(path) + ".npz"
    data = np.load(npz_path)
    params = model.params()
    if len(params) != len(data.files):
        raise ValueError(
            f"checkpoint has {len(data.files)} arrays but model expects {len(params)} "
            "— config mismatch between saved model and current architecture"
        )
    for i, p in enumerate(params):
        arr = data[f"w{i}"]
        if arr.shape != p.data.shape:
            raise ValueError(f"shape mismatch at param {i}: checkpoint {arr.shape} vs model {p.data.shape}")
        p.data = arr.copy()
    return model, tokenizer, config
