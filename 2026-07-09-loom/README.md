# Loom

A from-scratch tensor autograd engine, a GPT-style Transformer built
directly on top of it, a hand-coded Adam optimizer, and a training/
generation pipeline that turns a bundled text corpus into a small
language model that writes new text — no PyTorch, TensorFlow, or JAX
anywhere in the stack. NumPy is used strictly as a raw array/BLAS
library; every gradient in the system is derived and coded by hand in
`loom/tensor.py`, and proven correct by finite-difference gradient
checking against that hand-derived math.

## What it is

Everything between "matrix multiply" and "the model wrote a sentence" is
usually a black box: PyTorch's autograd, `nn.MultiheadAttention`,
`torch.optim.Adam`. Loom rebuilds that whole stack from first principles:

1. **`loom/tensor.py`** — a `Tensor` class that wraps a NumPy array and
   builds a dynamic computation graph as you use it. Every op (`+`, `*`,
   `@`, `**`, `exp`, `log`, `sqrt`, `tanh`, `relu`, `reshape`, `transpose`,
   indexing, `cat`, `softmax`, `log_softmax`, `masked_fill`) carries its
   own hand-derived backward pass, including correctly *undoing*
   NumPy's broadcasting on the way back (the part that's easy to get
   subtly wrong).
2. **`loom/nn.py`** — a GPT-style decoder-only Transformer built entirely
   out of `Tensor` operations: token + positional embeddings, multi-head
   causal self-attention, a GELU MLP, pre-LN residual blocks, and a
   weight-tied output head.
3. **`loom/optim.py`** — Adam, hand-coded from the original Kingma & Ba
   update rule against real `.grad` arrays.
4. **`loom/train.py` / `loom/generate.py`** — a training loop (LR warmup
   + cosine decay, gradient clipping, checkpointing) and autoregressive
   sampling (temperature / top-k / nucleus) that turns the trained
   weights into new text, live, in a chat loop.
5. **`loom/attention_trace.py` + `viz/attention_template.html`** — an
   interactive, self-contained HTML visualizer showing the model's real
   per-layer, per-head attention weights over real tokens, plus the real
   training loss curve.

Nothing in this repo imports an ML framework. If a gradient is wrong,
`./loom_cli gradcheck` catches it — every primitive op and the full model
end to end are checked against numerically estimated (finite-difference)
gradients before anything is trained.

## How to run it

```bash
cd 2026-07-09-loom
pip install numpy   # the only dependency

# Prove the autograd engine is correct: finite-difference gradient check
# of every primitive op, plus a full GPT forward -> loss -> backward pass.
./loom_cli gradcheck

# See the bundled corpora and model size presets.
./loom_cli info

# Train a GPT on the bundled fantasy-chronicle corpus. This is a from-
# scratch pure-NumPy autograd engine, not cuDNN -- expect ~165ms/step on
# the "tiny" preset (batch_size=16, single CPU core); the "quickstart"
# preset trains in seconds if you just want to see the pipeline run.
./loom_cli train --corpus all --preset tiny --steps 1500

# Generate text from a trained checkpoint.
./loom_cli generate --ckpt checkpoints/model.npz --prompt "Mira" --temperature 0.8 --top-k 20

# Talk to it interactively.
./loom_cli chat --ckpt checkpoints/model.npz

# Export the interactive attention visualizer -- open the resulting HTML
# file directly in a browser, no server needed.
./loom_cli viz --ckpt checkpoints/model.npz --prompt "Mira Ashgrove kept every wrong map"

# Run everything: the full test suite, then the whole pipeline live.
./demo.sh
```

A trained checkpoint (`checkpoints/model.npz`, 800 training steps on the
bundled corpus) and a real visualizer export (`viz/attention.html`) are
checked in so you can look at real output without training anything
first — open `viz/attention.html` straight in a browser.

## Full feature list

**Required (all 4 shipped):**
1. **Tensor autograd engine** (`loom/tensor.py`) — broadcasting-aware
   reverse-mode autodiff over NumPy arrays, gradient-checked against
   finite differences for every op.
2. **GPT-style Transformer from scratch** (`loom/nn.py`) — causal
   multi-head self-attention, GELU MLP, pre-LN residual blocks,
   weight-tied output head, all built on `Tensor`, gradient-checked end
   to end through a real forward/backward pass.
3. **From-scratch training pipeline** (`loom/optim.py`, `loom/train.py`)
   — hand-coded Adam, cross-entropy loss, gradient clipping, LR
   warmup+cosine schedule, checkpointing (bit-identical round-trip).
4. **Text generation** (`loom/generate.py`) — temperature / top-k /
   nucleus (top-p) autoregressive sampling, plus an interactive CLI chat
   loop against a trained model.

**Stretch (both shipped):**
5. **Interactive attention visualizer** (`loom/attention_trace.py` +
   `viz/attention_template.html`) — real per-layer/per-head attention
   heatmaps over real tokens with hover tooltips (you can literally watch
   the causal mask at work — future positions read exactly 0.0000), plus
   the real train/val loss curve. Self-contained HTML, data embedded
   inline, no server or fetch required.
6. **Configurable model presets + checkpointing** — `--preset
   quickstart/tiny/small` trading depth/width/context for speed, with
   save/load round-tripping to bit-identical logits.

**Plus, beyond the required gates:**
- `loom/gradcheck.py` — the correctness proof, reused by both the
  `gradcheck` CLI command and the automated test suite.
- A 43-test automated suite (`tests/test_loom.py`) and `demo.sh`, a
  runnable script that exercises every feature live.
- Two original bundled corpora (`corpus/chronicle.txt`,
  `corpus/lampwright.txt`) written for this project — no scraped data,
  so there are no licensing questions about what the model is trained on.

## Why I chose this today

This repo has already built a scalar-graph autodiff engine powering a
small MLP classifier (Cotangent, 2026-06-16). Tensor-shaped autograd is a
different, harder problem — broadcasting has to be *undone* correctly on
the backward pass, or gradients silently come out the wrong shape and the
whole system is quietly wrong in a way that's easy to miss without
gradient-checking. And attention is the mechanism half of modern software
is named after, that almost nobody has hand-derived the backward pass
for. Closing the loop from "here is a matrix" to "here is a model that
writes sentences it was never shown" — with every gradient checked, not
just assumed — felt like the most interesting unexplored corner in this
repo's history so far.

## Where a human could take this next

- **Speed**: this is intentionally a from-scratch, pure-NumPy engine, not
  a fast one. The biggest win would be operator fusion (fold LayerNorm's
  mean/var/normalize into one pass instead of five `Tensor` ops) and
  batching multiple attention heads into fewer, larger matmuls instead of
  slicing/reshaping per head.
- **Tokenization**: swap the char-level tokenizer for a from-scratch BPE
  tokenizer — the Transformer and training loop don't care, only
  `loom/tokenizer.py` and the embedding table size would change.
- **Scale**: the "small" preset (4 layers, dim 128) already runs; a human
  with a GPU-less afternoon could try KV-caching for faster generation,
  or add dropout/label smoothing and watch the val/train gap in the
  visualizer's loss chart change.
- **Corpus**: point `--corpus` at any text file and retrain — the
  pipeline doesn't know or care that the bundled corpora are fantasy
  fiction.
- **Bigger visualizer ambitions**: the attention export already captures
  full per-head matrices; a natural next step is animating them across
  training checkpoints to watch attention patterns *form* during
  training, not just inspecting the final ones.
