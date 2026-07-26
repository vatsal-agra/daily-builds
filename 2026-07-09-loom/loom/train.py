"""Training loop: minibatch cross-entropy over the char-level corpus, Adam
with LR warmup + cosine decay and gradient-norm clipping, periodic
train/val loss logging (written to JSON so the HTML visualizer can plot
it), and checkpointing."""
import json
import math

import numpy as np

from .nn import GPT
from .optim import Adam
from .tensor import cross_entropy
from .tokenizer import CharTokenizer


def lr_schedule(step, warmup_steps, total_steps, max_lr, min_lr_ratio=0.1):
    if step < warmup_steps:
        return max_lr * (step + 1) / max(1, warmup_steps)
    if step >= total_steps:
        return max_lr * min_lr_ratio
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    min_lr = max_lr * min_lr_ratio
    return min_lr + (max_lr - min_lr) * coeff


def compute_loss(model, x, y):
    logits = model.forward(x)
    B, T, V = logits.shape
    return cross_entropy(logits.reshape(B * T, V), y.reshape(-1))


def evaluate(model, dataset, iters, batch_size):
    losses = []
    for _ in range(iters):
        x, y = dataset.get_batch(batch_size, "val")
        losses.append(compute_loss(model, x, y).item())
    return float(np.mean(losses))


def train(model, tokenizer, dataset, steps=3000, batch_size=32, lr=3e-3, warmup=100,
          grad_clip=1.0, weight_decay=0.0, eval_interval=200, eval_iters=20,
          log_path=None, ckpt_path=None, verbose=True):
    opt = Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    history = []
    for step in range(steps):
        opt.lr = lr_schedule(step, warmup, steps, lr)
        x, y = dataset.get_batch(batch_size, "train")
        model.zero_grad()
        loss = compute_loss(model, x, y)
        loss.backward()
        grad_norm = opt.clip_grad_norm(grad_clip)
        opt.step()

        if step % eval_interval == 0 or step == steps - 1:
            val_loss = evaluate(model, dataset, eval_iters, batch_size)
            entry = {"step": step, "train_loss": loss.item(), "val_loss": val_loss,
                     "lr": opt.lr, "grad_norm": grad_norm}
            history.append(entry)
            if verbose:
                print(f"step {step:6d} | train_loss {loss.item():.4f} | "
                      f"val_loss {val_loss:.4f} | lr {opt.lr:.2e} | grad_norm {grad_norm:.3f}")

    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    if ckpt_path:
        save_checkpoint(ckpt_path, model, tokenizer, extra={"history": history})
    return history


def save_checkpoint(path, model, tokenizer, extra=None):
    params = model.parameters()
    arrays = {f"p{i}": p.data for i, p in enumerate(params)}
    meta = {"config": model.config(), "vocab": tokenizer.to_dict(),
            "n_params": len(params), "extra": extra or {}}
    np.savez(path, __meta__=json.dumps(meta), **arrays)


def load_checkpoint(path):
    d = np.load(path, allow_pickle=False)
    meta = json.loads(str(d["__meta__"]))
    model = GPT(**meta["config"])
    tokenizer = CharTokenizer.from_dict(meta["vocab"])
    params = model.parameters()
    assert len(params) == meta["n_params"], "checkpoint parameter count does not match model architecture"
    for i, p in enumerate(params):
        arr = d[f"p{i}"].astype(np.float64)
        assert arr.shape == p.data.shape, f"shape mismatch at param {i}: {arr.shape} vs {p.data.shape}"
        p.data = arr
    return model, tokenizer, meta
