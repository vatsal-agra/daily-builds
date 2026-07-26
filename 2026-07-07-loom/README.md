# Loom

A tiny LLM built entirely from scratch: a hand-written reverse-mode autograd
engine, a byte-level BPE tokenizer, a decoder-only Transformer, and a real
training loop. No PyTorch, no TensorFlow, no JAX, no `transformers`, no
autograd library of any kind. NumPy is used purely as an array/BLAS
substrate — the same role a hand-rolled matrix library would play — never
as a source of pre-built ML primitives.

Trained on Tiny Shakespeare (~1.1MB, public domain) end to end: tokenizer
training, model training, and text generation are all real, not mocked or
pre-baked. An **untrained** model sampled the same way produces byte
garbage with no word boundaries; the shipped **trained** checkpoint produces
speaker-header formatting, capitalization, word spacing, and archaic
Shakespearean pronouns it was never told about — real learned structure,
not memorized text (2000 steps on a 506K-parameter model doesn't get to
memorization).

## Why this, today

This repo's daily builds have a strong "from scratch" streak — SAT solvers,
version control systems, path tracers, a spreadsheet, crypto suites — but
never the thing that arguably matters most in 2026: the actual mechanism
powering an LLM. And building a real autograd engine is a *different kind*
of "from scratch" than re-implementing a well-known deterministic algorithm.
A SAT solver either returns the right answer or it doesn't. A subtly wrong
backward pass doesn't crash — it just quietly fails to learn, and the code
runs, prints a plausible-looking loss number, and looks fine. That made the
verification story the actual interesting problem here: gradient checking
every op against finite differences, and proving forward+backward+optimizer
are wired together correctly by overfitting a tiny batch to near-zero loss —
much closer to how real ML infrastructure is verified than to how a
deterministic-algorithm project gets tested.

## How to run it

```bash
pip install -r requirements.txt   # numpy only

# run everything: tests + a live walkthrough of every feature
./demo.sh

# or drive it by hand:
python3 -m loom.cli generate --checkpoint checkpoints/shakespeare \
  --prompt "ROMEO:" --max-new-tokens 200 --temperature 0.8 --top-k 40

python3 -m loom.cli chat --checkpoint checkpoints/shakespeare   # interactive REPL

python3 -m loom.cli viz --checkpoint checkpoints/shakespeare \
  --out loom_viz.html --prompt "ROMEO:"                          # open in a browser

# train your own from scratch on any text file:
python3 -m loom.cli train --corpus data/tinyshakespeare.txt --out checkpoints/mine \
  --vocab-size 512 --n-embd 96 --n-head 4 --n-layer 4 --block-size 96 \
  --batch-size 32 --steps 2000

python3 -m pytest tests/     # 67 tests: gradient checks, overfit test,
                              #  causal-mask leakage, tokenizer round-trip,
                              #  checkpoint validation, CLI error paths, ...
```

## Feature list

**Required (all fully working, not stubs):**

1. **From-scratch autograd engine** (`loom/tensor.py`) — a `Tensor` class
   with reverse-mode automatic differentiation over NumPy arrays:
   add/mul/matmul/pow/exp/log/tanh/sum/mean/reshape/transpose/getitem/cat,
   all broadcasting-aware, plus a `no_grad()` inference mode. Every op's
   gradient is verified against central-difference numerical gradients
   (17 tests) — nothing here is hand-waved.
2. **Byte-level BPE tokenizer** (`loom/tokenizer.py`) — trained from scratch
   via frequency-ranked pair merging; encode/decode round-trips *any* text
   exactly, including Unicode and punctuation never seen during training,
   because it falls back to raw bytes rather than an `<unk>` token.
3. **GPT-style decoder-only Transformer** (`loom/nn.py`) — token + learned
   positional embeddings, causal multi-head self-attention, pre-norm
   LayerNorm, GELU MLP blocks, weight-tied output head — built entirely as
   compositions of `Tensor` ops, so its backward pass is 100%
   engine-derived, not hand-written per layer.
4. **Real training pipeline** (`loom/train.py`, `loom/optim.py`) —
   from-scratch Adam (bias-corrected moments) + linear-warmup/cosine LR
   schedule + gradient clipping, trained end to end on Tiny Shakespeare:
   val loss 6.27 → 3.12, val perplexity 529 → 22.6 over 2000 steps (see
   table below), with checkpointing and cross-validated load/save.

**Stretch (both shipped):**

5. **Sampling strategies + interactive CLI** (`loom/generate.py`) —
   greedy, temperature, top-k, and top-p (nucleus) sampling, plus a
   `loom chat` REPL that completes whatever you type using the trained
   checkpoint.
6. **Interactive HTML visualizer** (`loom/viz.py`, `loom/pca.py`) — a
   self-contained page with (a) per-head causal attention-weight heatmaps
   for a live prompt run through the real trained model, (b) the actual
   training loss/perplexity curve, and (c) a from-scratch power-iteration
   PCA projection of the learned token embedding table (no `np.linalg.eig`/
   `svd` — the eigendecomposition is hand-rolled too). Built following this
   repo's dataviz conventions (validated categorical/sequential palette,
   crosshair tooltips, dark-mode-aware).

## Training run

`checkpoints/shakespeare/`: 4 layers, 4 heads, 96-dim, ~506K params,
vocab 512, 2000 steps, batch 32, block 96.

| step | train loss | val loss | val perplexity |
|---|---|---|---|
| 0 | 6.27 | 6.27 | 528.9 |
| 500 | 3.42 | 3.46 | 31.7 |
| 1000 | 3.20 | 3.22 | 25.1 |
| 1999 | 2.96 | 3.12 | 22.6 |

Sample completion (temperature 1.0, top-p 0.9):

```
First Citizen:
We then hest of race unfre strery and, your mouble desance;
Where death the and have thy do mam, thee.

FAUTESE:
And, my aty with nevery all man now at with the
```

## Adversarial review

[REVIEW.md](REVIEW.md) has the full account: 8 independent review passes
(line-by-line scan, missing-invariant audit, cross-file tracer, reuse,
simplification, efficiency, altitude, CLAUDE.md conventions) found 8 real,
independently-reproduced bugs — a `Dataset` off-by-one that crashed on
minimum-length corpus splits, a `top_k=0` that silently did nothing instead
of erroring, a wrong-gradient bug in `Tensor.transpose` for negative axes,
missing checkpoint shape/vocab validation, a raw `KeyError` from bad
tokenizer input, and more — all fixed with regression tests, plus a deeper
architectural fix (a `no_grad()` inference mode: 4x less peak memory, ~20%
faster generation, byte-for-byte identical output).

## Where a human could take this next

- **Speed**: swap the naive `O(merges × corpus)` BPE trainer for an
  incremental one (only rescan words touched by the last merge); replace
  `np.add.at` in the embedding gradient with a vectorized scatter-add;
  update Adam's moment buffers in place instead of allocating fresh arrays
  each step. None of these matter at this model's scale, but they'd matter
  a lot at 10-100x the parameters.
- **Scale up**: this was deliberately kept small (~506K params, 2000 steps)
  to keep the from-scratch NumPy engine's per-step cost reasonable. A human
  with a GPU and an afternoon could 50-100x the model size and get
  genuinely fluent Shakespeare-pastiche instead of structurally-correct
  gibberish.
- **KV caching**: `generate()` currently reprocesses the whole context
  window every step; a real KV cache would make long generations much
  cheaper and is a natural next engine feature.
- **Multi-file corpora / a real BPE special-token scheme** (`<|endoftext|>`
  document boundaries) so it can train on more than one concatenated text
  file without the model learning spurious continuations across document
  edges.
- **The `MultiHeadAttention.last_attn` side-channel** (REVIEW.md, "explicitly
  deferred") could become a proper hook/return-value contract if the
  visualizer ever needs to support KV-caching or batched multi-prompt runs.

## Repo layout

```
loom/
  tensor.py       autograd engine (Tensor, no_grad)
  functional.py   softmax/log_softmax/cross_entropy/layer_norm/gelu/causal_mask
  nn.py           Linear/Embedding/LayerNorm/MultiHeadAttention/TransformerBlock/GPT
  optim.py        Adam, LR schedule
  tokenizer.py    byte-level BPE
  data.py         corpus batching
  train.py        training loop, checkpointing
  generate.py     sampling (greedy/temperature/top-k/top-p)
  pca.py          from-scratch power-iteration PCA
  viz.py          interactive HTML visualizer
  cli.py          `loom` command-line entry point
data/tinyshakespeare.txt      training corpus (public domain)
checkpoints/shakespeare/      the shipped trained checkpoint
tests/                        67 tests (gradient checks, overfit test,
                               causal-mask leakage, tokenizer round-trip,
                               checkpoint validation, CLI error paths, viz)
demo.sh                       runs the tests + a live feature walkthrough
PLAN.md / REVIEW.md           Phase 1 plan / Phase 3 adversarial review
```
