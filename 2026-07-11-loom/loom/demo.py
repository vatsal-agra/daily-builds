"""One-command demo: trains a real (tiny) tokenizer + GPT on the bundled
corpus in well under a minute on CPU, contrasts an untrained model's babble
against the trained model's generations, and writes an interactive HTML
attention visualizer. Every number shown is produced live -- nothing here is
a canned/fixed output."""
import os
import tempfile
import time

import numpy as np

from .checkpoint import save as save_checkpoint
from .nn import GPT
from .sample import generate
from .tokenizer import ByteBPETokenizer
from .train import train
from .viz import render_html

_CORPUS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "corpus", "hollow_loom.txt")

DEMO_CONFIG = dict(
    num_merges=250,
    block_size=48,
    n_embd=48,
    n_head=4,
    n_layer=2,
    batch_size=16,
    steps=180,
    lr=4e-3,
    eval_every=30,
)


def run_demo(seed=0, viz_out="loom_demo_viz.html", log_fn=print):
    if not os.path.exists(_CORPUS_PATH):
        raise FileNotFoundError(f"bundled corpus not found at {_CORPUS_PATH}")
    with open(_CORPUS_PATH, encoding="utf-8") as f:
        text = f.read()

    log_fn(f"=== Loom demo (seed={seed}) ===")
    log_fn(f"corpus: {_CORPUS_PATH} ({len(text)} characters)")

    t0 = time.time()

    log_fn("\n--- training BPE tokenizer ---")
    tokenizer = ByteBPETokenizer()
    tokenizer.train(text, num_merges=DEMO_CONFIG["num_merges"])
    log_fn(f"vocab_size = {tokenizer.vocab_size}")

    log_fn("\n--- baseline: an UNTRAINED model's generation (random weights) ---")
    baseline_model = GPT(
        vocab_size=tokenizer.vocab_size, block_size=DEMO_CONFIG["block_size"],
        n_embd=DEMO_CONFIG["n_embd"], n_head=DEMO_CONFIG["n_head"], n_layer=DEMO_CONFIG["n_layer"],
        seed=seed,
    )
    baseline_text, _ = generate(baseline_model, tokenizer, prompt="The loom", max_new_tokens=120,
                                 temperature=1.0, top_k=None, top_p=None, seed=seed)
    log_fn(repr(baseline_text))

    # cross-entropy of the untrained model on a real chunk of the corpus,
    # as an objective (not eyeballed) measure of "before"
    probe_text = text[500:1500]
    probe_ids = np.array([tokenizer.encode(probe_text)[:DEMO_CONFIG["block_size"]]])
    baseline_loss = float(baseline_model(probe_ids[:, :-1], probe_ids[:, 1:])[1].data)
    log_fn(f"untrained cross-entropy on a real corpus excerpt: {baseline_loss:.4f} nats/token")

    log_fn(f"\n--- training for {DEMO_CONFIG['steps']} steps ---")
    ckpt_dir = tempfile.mkdtemp(prefix="loom_demo_")
    model, tokenizer, history = train(
        text, out_dir=ckpt_dir,
        num_merges=DEMO_CONFIG["num_merges"], block_size=DEMO_CONFIG["block_size"],
        n_embd=DEMO_CONFIG["n_embd"], n_head=DEMO_CONFIG["n_head"], n_layer=DEMO_CONFIG["n_layer"],
        batch_size=DEMO_CONFIG["batch_size"], steps=DEMO_CONFIG["steps"], lr=DEMO_CONFIG["lr"],
        eval_every=DEMO_CONFIG["eval_every"], seed=seed, log_fn=log_fn,
    )
    trained_loss = history[-1]["train_loss"]

    log_fn("\n--- trained model's generation (temperature=0.8, top_k=40) ---")
    trained_text, trace = generate(model, tokenizer, prompt="The loom", max_new_tokens=120,
                                    temperature=0.8, top_k=40, top_p=None, seed=seed, capture_attn=True)
    log_fn(repr(trained_text))

    elapsed = time.time() - t0
    log_fn(f"\n--- summary ---")
    log_fn(f"untrained probe cross-entropy: {baseline_loss:.4f} nats/token")
    log_fn(f"trained final train_loss:      {trained_loss:.4f} nats/token")
    improvement = baseline_loss - trained_loss
    log_fn(f"improvement:                   {improvement:.4f} nats/token "
           f"({'model learned something real' if improvement > 0.5 else 'WARNING: little improvement'})")
    log_fn(f"total wall-clock time: {elapsed:.1f}s")

    html = render_html(model, tokenizer, {"history": history}, trace, prompt="The loom")
    with open(viz_out, "w", encoding="utf-8") as f:
        f.write(html)
    log_fn(f"wrote interactive visualizer to {viz_out} ({len(html)} bytes)")
    log_fn(f"checkpoint saved to {ckpt_dir}")

    return {
        "baseline_loss": baseline_loss,
        "trained_loss": trained_loss,
        "history": history,
        "elapsed_s": elapsed,
        "checkpoint_dir": ckpt_dir,
        "viz_path": viz_out,
        "baseline_text": baseline_text,
        "trained_text": trained_text,
    }
