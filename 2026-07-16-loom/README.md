# Loom

A tiny GPT-style language model built entirely from scratch in Python: a
hand-rolled reverse-mode tensor autodiff engine, a byte-pair-encoding
tokenizer, a decoder-only multi-head causal-attention Transformer, an
Adam-trained optimizer loop with LR warmup/cosine decay and gradient
clipping, and autoregressive sampling (greedy / temperature / top-k /
top-p). No PyTorch, no JAX, no autograd library — every operator's forward
*and* backward pass is written by hand and gradient-checked against
numerical finite differences.

See [PLAN.md](PLAN.md) for the original design and [REVIEW.md](REVIEW.md)
for the adversarial-review pass that hardened it.

## Why this, today

Every prior build in this repo's ledger has picked one classical system —
a renderer, a SAT solver, a database, a VCS, a chess engine, a compression
codec, even a scalar autodiff engine + MLP (Cotangent, 2026-06-16) — and
implemented it from first principles. None had built the architecture that
defines this era: a Transformer language model. Loom closes that gap, and
does it the hard way: the backward pass through causal softmax attention,
LayerNorm, and GELU each require real matrix calculus, not just
chain-ruling scalar multiplies — a meaningfully harder derivation than
Cotangent's scalar case, applied to the architecture that actually matters
right now.

## Honesty about scale

This is a **nanoGPT-scale** model: small `d_model`, a handful of layers and
heads, a short context window, trained for a few minutes of CPU-only NumPy
on an ~8.7 KB original corpus (`data/corpus.txt`, an authored fable written
for this project — no scraped or copyrighted text). At the settings below,
training loss drops from ~6.5 (random-guess territory for a ~400-token
vocabulary) to well under 1.0 within a few hundred steps — at that point the
tiny model is substantially *memorizing* its small corpus rather than
learning generalizable language structure, and generated text reads as
recognizable, sometimes verbatim, fragments of the training fable rather
than novel prose. That's an honest, expected outcome of "a few thousand
words of training data + a few-hundred-thousand-parameter model" — the
point of this build is a complete, correct, from-scratch pipeline
(tokenizer -> autodiff -> transformer -> optimizer -> sampler), gradient-
checked at every step, not a large or fluent model. Train on more/your own
text via `--corpus` for less memorization-flavored output.

## Quick start

```
pip install -r requirements.txt

# 1. Train a byte-level BPE tokenizer on the bundled corpus
python3 loom.py train-tokenizer --vocab-size 400 --out tokenizer.json

# 2. Train the model (≈2 minutes on CPU at these settings)
python3 loom.py train --tokenizer tokenizer.json --out checkpoint.npz --steps 600

# 3. Generate text
python3 loom.py generate --checkpoint checkpoint.npz --tokenizer tokenizer.json \
    --prompt "Old Maren" --max-new-tokens 150 --temperature 0.8 --top-k 40

# 4. Chat REPL
python3 loom.py chat --checkpoint checkpoint.npz --tokenizer tokenizer.json

# 5. Visualize real attention weights for a prompt
python3 loom.py attn-viz --checkpoint checkpoint.npz --tokenizer tokenizer.json \
    --prompt "Old Maren said" --out attention.html   # open in a browser

# Gradient-check the whole autodiff engine
python3 loom.py gradcheck

# Full verification (32 unit tests + 17 end-to-end CLI checks)
bash demo.sh
```

## Feature list

**Required (all 4 shipped, fully working end-to-end):**

1. **Byte-level BPE tokenizer, trained from scratch** (`loom/tokenizer.py`)
   — merge-pair counting, iterative merging to a target vocab size, exact
   `encode`/`decode` round-trip (verified on ASCII, unicode, emoji, and the
   empty string), JSON persistence.
2. **Tensor autodiff engine + GPT transformer** (`loom/tensor.py`,
   `loom/model.py`) — a `Tensor` computation-graph class with correct
   forward/backward for every op a real Transformer needs (broadcasting
   add/mul/pow/div, batched matmul, reshape/permute, softmax, layer norm,
   GELU, embedding gather, cross-entropy); 17/17 ops gradient-checked
   against numerical finite differences, including a full transformer
   block. Multi-head causal self-attention verified to have **zero
   information leakage** from future tokens (explicit before/after-diff
   test, not just "it looks right").
3. **End-to-end training loop** (`loom/train.py`, `loom/optim.py`) — Adam
   with bias-corrected moments, linear-warmup + cosine-decay LR schedule,
   global gradient-norm clipping, batched next-token cross-entropy
   training with measurable loss decrease, checkpoint save/reload
   (`.npz`, byte-identical parameters and forward output after reload).
4. **Autoregressive generation** (`loom/generate.py`) — greedy, temperature,
   top-k, and top-p (nucleus) sampling, exposed via `generate` and an
   interactive `chat` REPL.

**Stretch (1 shipped in full, per the plan's "ship at least 1"):**

5. **Interactive attention-weights visualizer** (`loom/attn_viz.py`,
   `attn-viz` command) — runs a real forward pass on a user prompt and
   renders the actual captured per-layer/per-head attention matrices as a
   self-contained, theme-aware (light/dark) HTML heatmap: layer/head
   picker buttons, hover/focus tooltip showing the exact weight and the
   query->key token pair, and causally-masked (future-token) cells
   visually distinguished from valid-but-near-zero attention. Verified
   with a headless-Chromium smoke test (loads clean, zero JS console
   errors, tooltip and layer/head switching confirmed, both color schemes
   screenshotted).

## Adversarial review highlights

Six real issues were found and fixed in `REVIEW.md` — worth calling out
here: `--seed` silently did **not** control weight initialization (only
batch sampling), so two different seeds produced byte-identical starting
weights; an off-by-one in corpus-length validation crashed with a raw
NumPy `ValueError: high <= 0` instead of a clean message on a
corpus exactly one token too short; `--steps 0` crashed with an unhandled
`IndexError`; missing/corrupt input files (corpus, tokenizer, checkpoint)
surfaced raw Python tracebacks; two autodiff ops (`cat`, `__getitem__`)
were implemented and gradient-checked but never actually used by the
model; and `Tensor.shape` was a stale-able plain attribute rather than a
property. All six are fixed and regression-tested.

## Architecture

```
corpus.txt --BPE training--> tokenizer.json
     |
     v
token ids --embed + positional--> N x [ LayerNorm -> causal MHSA -> +residual
                                          LayerNorm -> MLP(GELU)  -> +residual ]
                                   --> LayerNorm -> Linear --> logits
     |
     v
cross-entropy loss --backward (hand-derived autodiff)--> Adam + LR schedule
     |
     v
sampling (greedy / temperature / top-k / top-p) --> generated text
     |
     v
captured attention weights --> interactive HTML heatmap
```

## Where a human could take this next

- **Rotary or ALiBi positional encoding** instead of learned absolute
  positions, so the model generalizes past its trained context length
  instead of resetting position on every sliding-window generation step.
- **KV-caching** for O(1)-per-token generation instead of recomputing the
  full forward pass at every sampling step (fine at this scale, painful at
  any larger one).
- **A bigger, non-memorized corpus** (megabytes, not kilobytes) to see the
  model actually generalize instead of mostly memorize — the pipeline
  (tokenizer/model/training/sampling) is architecture-complete for this
  today with no code changes, just more data and more steps.
- **Mixed precision / vectorized batching across heads** without the
  Python-level loop-free NumPy already used, for real wall-clock speedups.
- **A tiny RLHF or DPO loop** on top of the existing autodiff engine and
  optimizer, since both are already general enough to backprop through an
  arbitrary scalar loss.

## Verification

- `python3 loom.py gradcheck` — 17/17 ops incl. a full transformer block.
- `python3 -m unittest tests.test_loom -v` — 32 unit tests.
- `bash demo.sh` — 17 end-to-end checks against the real CLI (training,
  generation, chat, attention viz, and edge cases: missing files,
  `--steps 0`, whitespace-only prompts), all green.
