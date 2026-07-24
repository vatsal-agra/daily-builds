"""Checkpoint save/load: model weights + config + tokenizer + training
metadata, bundled into one directory so a checkpoint is fully self
describing and reloadable without any external state."""
import json
import os

import numpy as np

from .model import GPT, GPTConfig
from .tokenizer import BPETokenizer


def save(path, model: GPT, tokenizer: BPETokenizer, meta: dict):
    os.makedirs(path, exist_ok=True)
    cfg = model.cfg
    with open(os.path.join(path, "config.json"), "w") as f:
        json.dump({
            "vocab_size": cfg.vocab_size,
            "block_size": cfg.block_size,
            "n_layer": cfg.n_layer,
            "n_head": cfg.n_head,
            "n_embd": cfg.n_embd,
            "dropout": cfg.dropout,
        }, f, indent=2)
    tokenizer.save(os.path.join(path, "tokenizer.json"))
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    params = model.parameters()
    arrays = {f"p{i}": p.data.astype(np.float32) for i, p in enumerate(params)}
    np.savez_compressed(os.path.join(path, "weights.npz"), **arrays)


def load(path):
    with open(os.path.join(path, "config.json")) as f:
        cfg_dict = json.load(f)
    cfg = GPTConfig(**cfg_dict)
    model = GPT(cfg)
    tokenizer = BPETokenizer.load(os.path.join(path, "tokenizer.json"))
    meta_path = os.path.join(path, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)

    weights = np.load(os.path.join(path, "weights.npz"))
    params = model.parameters()
    if len(weights.files) != len(params):
        raise ValueError(
            f"checkpoint has {len(weights.files)} tensors but model config "
            f"produces {len(params)} parameters -- config/weights mismatch"
        )
    for i, p in enumerate(params):
        arr = weights[f"p{i}"].astype(np.float64)
        if arr.shape != p.data.shape:
            raise ValueError(f"param {i} shape mismatch: checkpoint {arr.shape} vs model {p.data.shape}")
        p.data = arr
    return model, tokenizer, meta
