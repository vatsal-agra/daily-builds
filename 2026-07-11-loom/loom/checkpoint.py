"""Checkpoint save/load: model hyperparameters + parameters + tokenizer +
training history, all in one directory so a run can be resumed or sampled
from later exactly as it left off."""
import json
import os

import numpy as np

from .nn import GPT
from .tokenizer import ByteBPETokenizer


def save(dir_path, model, tokenizer, history=None, extra=None):
    os.makedirs(dir_path, exist_ok=True)
    params = model.parameters()
    np.savez(os.path.join(dir_path, "params.npz"), **{f"p{i}": p.data for i, p in enumerate(params)})
    meta = {
        "vocab_size": model.vocab_size,
        "block_size": model.block_size,
        "n_embd": model.n_embd,
        "n_head": model.n_head,
        "n_layer": model.n_layer,
        "history": history or [],
        "extra": extra or {},
    }
    with open(os.path.join(dir_path, "meta.json"), "w") as f:
        json.dump(meta, f)
    tokenizer.save(os.path.join(dir_path, "tokenizer.json"))


def load(dir_path):
    with open(os.path.join(dir_path, "meta.json")) as f:
        meta = json.load(f)
    model = GPT(
        vocab_size=meta["vocab_size"],
        block_size=meta["block_size"],
        n_embd=meta["n_embd"],
        n_head=meta["n_head"],
        n_layer=meta["n_layer"],
    )
    npz = np.load(os.path.join(dir_path, "params.npz"))
    params = model.parameters()
    if len(npz.files) != len(params):
        raise ValueError(
            f"checkpoint has {len(npz.files)} parameter arrays but model architecture "
            f"expects {len(params)} -- checkpoint is incompatible with this model shape"
        )
    for i, p in enumerate(params):
        arr = npz[f"p{i}"]
        if arr.shape != p.data.shape:
            raise ValueError(f"checkpoint param {i} has shape {arr.shape}, expected {p.data.shape}")
        p.data = arr.astype(np.float64)
    tokenizer = ByteBPETokenizer.load(os.path.join(dir_path, "tokenizer.json"))
    return model, tokenizer, meta
