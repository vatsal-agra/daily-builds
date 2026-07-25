# Loom

A GPT-style decoder-only Transformer language model, built entirely from
scratch — tokenizer, self-attention, hand-derived backpropagation, and the
training loop — in Python + NumPy. No `torch`, `jax`, `transformers`, or
autograd library anywhere in this project.

**Status: Phase 3 (adversarial review) in progress.** All four required
features are implemented, tested, and trained end-to-end on the real
corpus — loss fell from ~5.97 to ~0.18-0.20 with train/val tracking closely
(no runaway overfitting), and the trained model produces genuinely
grammatical, on-theme fable continuations. A hostile self-review found and
fixed 6 real issues (see [`REVIEW.md`](REVIEW.md)), including a corpus
data-generation bug and a silent-corruption path for diverged gradients;
the model is being retrained from scratch on the corrected corpus before
shipping. See [`PLAN.md`](PLAN.md) for the full architecture and feature
list.

## What's implemented so far

- `loom/tokenizer.py` — byte-level BPE, trained from scratch on the corpus.
- `loom/layers.py`, `loom/model.py` — GPT (embedding, causal multi-head
  self-attention, LayerNorm, GELU MLP, tied output head), every layer with
  a hand-written `backward()`.
- `loom/optimizer.py` — AdamW, global-norm grad clipping, warmup+cosine LR.
- `loom/generate.py` — naive + KV-cached autoregressive sampling.
- `loom/train.py`, `loom/cli.py` — training loop and `loom train|generate|bench|viz` CLI.
- `viz/visualizer.html` — attention-heatmap + generation step-through viewer.
- `tests/` — gradient checks, tokenizer round-trip, causal-mask leakage
  check, overfit sanity check, and generation parity/determinism checks —
  all passing.

Next: finish the real training run on `corpus/fables.txt`, confirm sample
quality, then Phase 3 (adversarial review) and Phase 4 (KV-cache stretch +
polish).
