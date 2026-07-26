"""Training loop: forward -> cross-entropy loss -> backward -> Adam step,
with gradient clipping and checkpointing."""
import time

import numpy as np

from . import checkpoint
from .data import TextDataset
from .nn import GPT
from .optim import Adam
from .tokenizer import ByteBPETokenizer


def train(
    text,
    out_dir,
    num_merges=300,
    block_size=64,
    n_embd=64,
    n_head=4,
    n_layer=2,
    batch_size=16,
    steps=200,
    lr=3e-3,
    grad_clip=1.0,
    eval_every=25,
    seed=0,
    log_fn=print,
):
    if len(text) < 20:
        raise ValueError("training corpus is too small (need at least 20 characters)")

    rng = np.random.default_rng(seed)

    tokenizer = ByteBPETokenizer()
    tokenizer.train(text, num_merges=num_merges)
    ids = tokenizer.encode(text)
    if len(ids) < block_size + 2:
        raise ValueError(
            f"corpus encodes to only {len(ids)} tokens, need > block_size+1={block_size + 1}; "
            "use a longer corpus or pass a smaller --block-size"
        )
    dataset = TextDataset(ids, block_size=block_size)

    model = GPT(
        vocab_size=tokenizer.vocab_size,
        block_size=block_size,
        n_embd=n_embd,
        n_head=n_head,
        n_layer=n_layer,
        seed=seed,
    )
    opt = Adam(model.parameters(), lr=lr)

    history = []
    t0 = time.time()
    for step in range(1, steps + 1):
        xb, yb = dataset.get_batch("train", batch_size, block_size, rng)
        _, loss = model(xb, yb)
        opt.zero_grad()
        loss.backward()
        opt.clip_grad_norm(grad_clip)
        opt.step()

        if step % eval_every == 0 or step == 1 or step == steps:
            xv, yv = dataset.get_batch("val", batch_size, block_size, rng)
            _, vloss = model(xv, yv)
            entry = {"step": step, "train_loss": float(loss.data), "val_loss": float(vloss.data),
                      "elapsed_s": round(time.time() - t0, 2)}
            history.append(entry)
            log_fn(f"step {step:5d}/{steps} | train_loss {entry['train_loss']:.4f} "
                   f"| val_loss {entry['val_loss']:.4f} | {entry['elapsed_s']:.1f}s")

    checkpoint.save(out_dir, model, tokenizer, history=history,
                     extra={"steps": steps, "batch_size": batch_size, "lr": lr, "seed": seed})
    return model, tokenizer, history
