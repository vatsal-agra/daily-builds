"""Checkpoint save/load: model weights (npz) + architecture config (json)."""
import json
import os

import numpy as np

from .nn import GPT


def save_checkpoint(model, config, weights_path, config_path):
    arrays = {name: p.data for name, p in model.named_parameters()}
    np.savez(weights_path, **arrays)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def load_checkpoint(weights_path, config_path):
    missing = [p for p in (weights_path, config_path) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"checkpoint file(s) not found: {missing}. "
            "Train a model first, e.g.: python3 cli.py train --out-dir <that directory>"
        )
    with open(config_path) as f:
        config = json.load(f)
    model = GPT(
        vocab_size=config["vocab_size"],
        n_embd=config["n_embd"],
        n_head=config["n_head"],
        n_layer=config["n_layer"],
        block_size=config["block_size"],
    )
    arrays = np.load(weights_path)
    named = dict(model.named_parameters())
    missing = set(named) - set(arrays.files)
    extra = set(arrays.files) - set(named)
    if missing:
        raise ValueError(f"checkpoint is missing parameters: {sorted(missing)}")
    if extra:
        raise ValueError(f"checkpoint has unexpected parameters: {sorted(extra)}")
    for name, p in named.items():
        arr = arrays[name]
        if arr.shape != p.data.shape:
            raise ValueError(
                f"shape mismatch for {name}: checkpoint has {arr.shape}, "
                f"model expects {p.data.shape}"
            )
        p.data = arr.astype(np.float64)
    return model, config
