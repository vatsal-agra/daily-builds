"""Training loop: batches next-token prediction over the tokenized corpus,
cross-entropy loss through the hand-rolled autodiff graph, Adam + warmup/
cosine LR schedule + grad-norm clipping, with checkpointing.
"""
from __future__ import annotations

import time
import numpy as np

from loom.model import GPT
from loom.optim import Adam, clip_grad_norm, lr_schedule
from loom.tensor import cross_entropy


def min_tokens_required(block_size: int) -> int:
    """Need one extra token past the final window so every sampled x has a
    valid shifted-by-one target y."""
    return block_size + 2


def get_batch(ids: np.ndarray, block_size: int, batch_size: int, rng: np.random.Generator):
    if len(ids) < min_tokens_required(block_size):
        raise ValueError(
            f"corpus has only {len(ids)} tokens, need at least "
            f"{min_tokens_required(block_size)} for block_size={block_size}")
    starts = rng.integers(0, len(ids) - block_size - 1, size=batch_size)
    x = np.stack([ids[s:s + block_size] for s in starts])
    y = np.stack([ids[s + 1:s + block_size + 1] for s in starts])
    return x, y


def train(model: GPT, ids: np.ndarray, steps: int, batch_size: int = 16, base_lr: float = 3e-3,
          warmup_steps: int | None = None, grad_clip: float = 1.0, seed: int = 0,
          log_every: int = 50, on_log=None) -> list[tuple[int, float]]:
    rng = np.random.default_rng(seed)
    params = model.parameters()
    opt = Adam(params, lr=base_lr)
    warmup_steps = warmup_steps if warmup_steps is not None else max(1, steps // 20)

    history = []
    t0 = time.time()
    for step in range(steps):
        x, y = get_batch(ids, model.block_size, batch_size, rng)
        logits = model(x)
        B, T, V = logits.shape
        loss = cross_entropy(logits.reshape(B * T, V), y.reshape(B * T))

        opt.zero_grad()
        loss.backward()
        clip_grad_norm(params, grad_clip)
        lr = lr_schedule(step, base_lr, warmup_steps, steps)
        opt.step(lr)

        loss_val = float(loss.data)
        if step % log_every == 0 or step == steps - 1:
            history.append((step, loss_val))
            if on_log:
                on_log(step, loss_val, lr, time.time() - t0)
    return history


def save_checkpoint(path: str, model: GPT) -> None:
    arrays = {f"param_{i}": p.data for i, p in enumerate(model.parameters())}
    np.savez(path, config=np.array([model.config()], dtype=object), **arrays)


def load_checkpoint(path: str) -> GPT:
    data = np.load(path, allow_pickle=True)
    config = data["config"][0]
    model = GPT(**config)
    params = model.parameters()
    for i, p in enumerate(params):
        p.data = data[f"param_{i}"]
    return model
