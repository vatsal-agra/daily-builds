"""Training loop: forward -> cross-entropy loss -> backward -> Adam step."""
import time
import numpy as np

from .nn import GPT, cross_entropy_loss
from .optim import Adam, lr_schedule
from .tokenizer import CharTokenizer, BPETokenizer
from .data import load_corpus, train_val_split, get_batch
from .checkpoint import save_checkpoint


def evaluate(model, ids, block_size, batch_size, rng, n_batches=5):
    losses = []
    for _ in range(n_batches):
        x, y = get_batch(ids, batch_size, block_size, rng)
        logits = model(x, training=False)
        loss = cross_entropy_loss(logits, y)
        losses.append(loss.item())
    return float(np.mean(losses))


def train(
    corpus_path,
    out_path,
    d_model=64,
    n_heads=4,
    n_layers=3,
    d_ff=256,
    block_size=64,
    batch_size=32,
    steps=2000,
    lr=3e-3,
    warmup_steps=100,
    grad_clip=1.0,
    seed=0,
    log_every=100,
    eval_every=200,
    on_log=None,
    tokenizer_kind="char",
    bpe_merges=200,
    dropout_p=0.1,
):
    rng = np.random.default_rng(seed)
    np.random.seed(seed)

    text = load_corpus(corpus_path)
    if tokenizer_kind == "char":
        tokenizer = CharTokenizer(text)
        ids = tokenizer.encode(text)
    elif tokenizer_kind == "bpe":
        tokenizer = BPETokenizer()
        ids = tokenizer.train(text, num_merges=bpe_merges)
    else:
        raise ValueError(f"unknown tokenizer_kind: {tokenizer_kind!r}")
    train_ids, val_ids = train_val_split(ids, val_fraction=0.1)

    model = GPT(tokenizer.vocab_size, d_model, n_heads, n_layers, d_ff, block_size, dropout_p=dropout_p)
    opt = Adam(model.params(), lr=lr)

    config = {
        "vocab_size": tokenizer.vocab_size,
        "d_model": d_model,
        "n_heads": n_heads,
        "n_layers": n_layers,
        "d_ff": d_ff,
        "max_seq_len": block_size,
    }

    # Small corpora overfit fast: the checkpoint with the lowest validation
    # loss is usually not the last one, so track it separately and ship that
    # rather than whatever the final, possibly-memorizing step happens to be.
    best_val_loss = float("inf")
    best_params = None

    history = []
    t0 = time.time()
    for step in range(steps):
        cur_lr = lr_schedule(step, warmup_steps, steps, lr)
        opt.lr = cur_lr

        x, y = get_batch(train_ids, batch_size, block_size, rng)
        logits = model(x, training=True)
        loss = cross_entropy_loss(logits, y)

        opt.zero_grad()
        loss.backward()
        opt.clip_grad_norm(grad_clip)
        opt.step()

        if step % log_every == 0 or step == steps - 1:
            msg = f"step {step:5d}/{steps} | loss {loss.item():.4f} | lr {cur_lr:.5f} | {time.time()-t0:.1f}s"
            history.append({"step": step, "train_loss": loss.item(), "lr": cur_lr})
            if on_log:
                on_log(msg)
            else:
                print(msg)

        if step % eval_every == 0 or step == steps - 1:
            val_loss = evaluate(model, val_ids, block_size, min(batch_size, 16), rng)
            is_best = val_loss < best_val_loss
            if is_best:
                best_val_loss = val_loss
                best_params = [p.data.copy() for p in model.params()]
            msg = f"           val_loss {val_loss:.4f}{'  (best)' if is_best else ''}"
            if history:
                history[-1]["val_loss"] = val_loss
            if on_log:
                on_log(msg)
            else:
                print(msg)

    # Ship the best-validation-loss weights, not necessarily the final step's.
    if best_params is not None:
        for p, data in zip(model.params(), best_params):
            p.data = data
    save_checkpoint(out_path, model, tokenizer, config)
    return model, tokenizer, config, history, best_val_loss
