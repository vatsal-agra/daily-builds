# Loom

A GPT-style language model built entirely from scratch: a hand-derived
reverse-mode automatic differentiation engine, a from-scratch byte-pair
encoding tokenizer, a decoder-only transformer, and an Adam optimizer —
trained on the public-domain Tiny Shakespeare corpus, with a live web UI
for text generation and attention visualization.

No PyTorch, TensorFlow, JAX, or tinygrad anywhere in this repo. The only
third-party dependency is NumPy, used purely as a fast ndarray + BLAS
matmul substrate — every gradient in `loom/engine.py` is hand-derived and
verified against finite-difference numerical gradients.

```
"To be, or not to be:" -> attention heatmap, per layer, per head, in the browser
"ROMEO:"                -> real generated text from a checkpoint trained end-to-end below
```

## Quickstart

```bash
cd 2026-07-24-loom
pip install -r requirements.txt        # numpy only

# A trained checkpoint already ships in checkpoints/loom-shakespeare/ --
# generate from it immediately:
python3 -m loom.cli generate "ROMEO:" --max-new-tokens 200 --temperature 0.8 --top-k 40

# Or launch the interactive web UI:
python3 -m loom.cli serve
# -> open http://127.0.0.1:8420

# Or run the full verification suite (tests + CLI + live server round trip):
bash demo.sh

# Or train your own from scratch (~15-20 min on 4 CPU cores):
python3 -m loom.cli train --max-steps 3000
```

## What it is

Loom implements the entire path from raw text to generated text without
reaching for a machine-learning framework at any point:

1. **`loom/engine.py`** — a `Tensor` class wrapping a NumPy array with a
   dynamic autograd graph built from closures, and a topological-sort
   `.backward()` — the same design as Karpathy's `micrograd`, generalized
   from scalars to n-dimensional tensors. Every op (`+`, `*`, `matmul`,
   broadcasting, `reshape`/`transpose`, `sum`/`mean`, `exp`/`log`, `relu`,
   `gelu`, `softmax`, `layer_norm`, `embedding`, `dropout`,
   `cross_entropy`) carries its own hand-derived backward pass.
2. **`loom/tokenizer.py`** — byte-pair encoding trained from scratch:
   starts from the 256 raw bytes, greedily learns the most-frequent
   adjacent-pair merges weighted by word frequency (not a linear scan of
   the whole corpus per merge — the thing that makes training on a
   megabyte-scale corpus fast in pure Python), and always falls back to
   raw bytes for text it's never seen, so encoding can never fail.
3. **`loom/model.py`** — a GPT-2-style decoder-only transformer (causal
   multi-head self-attention, learned positional embeddings, pre-LN
   blocks, GELU MLP, weight-tied output head) built entirely from
   `engine.py` primitives.
4. **`loom/optim.py`** — Adam (Kingma & Ba, 2014) with decoupled weight
   decay, applied only to weight matrices (not LayerNorm gain/bias, a
   deliberate fix — see `REVIEW.md`).
5. **`loom/train.py`** — the training loop: random context-window
   batching, periodic validation-loss estimation, checkpointing, and a
   generated sample printed at every eval so you can watch it learn.
6. **`loom/generate.py`** — autoregressive sampling with temperature,
   top-k, and top-p (nucleus) filtering implemented directly on the raw
   logit array, plus a function that extracts the real per-layer,
   per-head attention weights from an actual forward pass.
7. **`loom/server.py` + `static/`** — a stdlib-only `http.server` backend
   (no Flask/FastAPI) serving a vanilla HTML/CSS/JS single-page UI: a live
   training-loss chart, a generation panel with adjustable sampling
   parameters, and an attention-heatmap visualizer. All model logic stays
   server-side; the browser only ever makes real HTTP calls.

## Feature list

**Required (all four implemented and tested):**

1. From-scratch reverse-mode autodiff engine, gradient-checked op-by-op
   against finite differences (`tests/test_engine.py`, 17 groups) and
   end-to-end on the full model (sampled weight entries match numerical
   gradients to `1e-12`).
2. From-scratch BPE tokenizer with byte fallback for arbitrary unseen
   input — never raises an unknown-token error.
3. GPT-style transformer trained on real text (Tiny Shakespeare, ~1.1MB)
   until loss demonstrably drops from the random-init baseline
   (`ln(512) = 6.24`) to a clearly lower plateau (final: train loss
   **3.47**, val loss **3.65** after 3000 Adam steps).
4. Autoregressive generation with temperature/top-k/top-p sampling
   implemented from scratch on the logit tensor, exposed via both a CLI
   and the web UI.

**Stretch (both implemented):**

5. Interactive web UI (`loom serve`) — chat-style prompt-to-generation
   panel, a live-updating training-loss chart, all backed by real HTTP
   calls to the loaded checkpoint.
6. Attention visualizer — runs a real forward pass and renders the actual
   per-layer, per-head attention-weight matrix as a heatmap, with
   click-to-switch layer/head selectors.

## Why I built this today

Every prior daily build that touched "intelligence" reached for something
ML-adjacent (HNSW vector search in VecNN, classical CV in Optic) but none
had built the thing everyone actually means by "AI" now: a transformer
trained end-to-end from raw text. The interesting engineering constraint
isn't the transformer architecture itself (that part's well-trodden) —
it's that every op needs a *correct*, hand-derived backward pass, and a
wrong gradient doesn't crash, it just silently fails to learn. That
"quietly wrong" failure mode is exactly why the test suite leans so hard
on finite-difference gradient checking rather than just "does the loss go
down eventually."

## Results

Trained for 3000 Adam steps (~17.5 minutes on 4 CPU cores) on the full
Tiny Shakespeare corpus with a small model (3 layers, 4 heads, 64-dim
embeddings, 64-token context, 512-token BPE vocab, 186,944 parameters):

| step | train loss | val loss |
|-----:|-----------:|---------:|
|    1 |       6.25 |        — |
|  150 |       5.04 |     5.01 |
|  900 |       3.93 |     3.95 |
| 1800 |       3.66 |     3.73 |
| 3000 |   **3.47** |   **3.65** |

(random-init baseline: `ln(512) = 6.24`)

Sample generation at the final checkpoint (`temperature=0.8, top_k=40`):

```
ROMEO:
That not too, roving out offe.

MENROLILIARGENENCE:
That will not acres, I tear?

GLOUCIONTESTUS:
Go, I gone, fook me, if un
And grace, I must bet---fore it wove you?
```

Not Shakespeare — this is a ~187K-parameter model trained for under 20
minutes on a CPU — but it has clearly learned real structure: consistent
word-length statistics, plausible English letter patterns, correct
script-style formatting (`ALL CAPS NAME:` followed by dialogue), stage
punctuation, and line breaks in the right places. That's the honest,
verifiable signature of a working training loop, not a templated string.

## Verification

```bash
bash demo.sh
```

Runs, in order: `tests/test_engine.py` (autodiff gradient checks),
`tests/test_tokenizer.py`, `tests/test_model.py` (including a causal-mask
leak test and a tiny-batch overfit test — a much stronger correctness gate
than "loss goes down eventually"), `tests/test_integration.py` (a real
small end-to-end training run plus a real subprocess `loom.server` driven
over actual HTTP), then a CLI generation, a CLI attention inspection, and
a live HTTP server round trip against the shipped checkpoint. All green.

See [REVIEW.md](REVIEW.md) for the adversarial-review pass: four real bugs
found and fixed (a server crash on `NaN`/`Infinity` JSON fields, a CLI
argv-parsing bug, a raw-traceback-on-missing-checkpoint, and weight decay
incorrectly hitting LayerNorm params), plus a full list of what was
specifically hunted for and confirmed correct.

## Where a human could take this next

- **Scale it up.** The architecture has no hard ceiling at this size —
  more layers/heads/embedding dim and more training steps would move loss
  meaningfully lower (nanoGPT-scale runs on real Shakespeare get well
  under 1.5 with more compute). The current size was chosen so the whole
  pipeline trains in well under 20 minutes on ordinary CPU cores.
- **KV-cache generation.** `generate()` currently recomputes the full
  forward pass for every new token (documented, deliberate scope
  decision at this model size) — a real KV cache would make longer
  generations and a bigger model practical.
- **Multi-head attention rollup / induction-head analysis.** The
  attention visualizer already exposes the raw weight matrices; a natural
  next step is automated analysis (e.g. detecting induction heads) on top
  of what's already being rendered.
- **A bigger/different corpus.** Swap `data/shakespeare.txt` for anything
  else — the tokenizer and training loop are corpus-agnostic.
- **Mixed precision / vectorization.** `engine.py` operates in float64 for
  gradient-check precision; a production-oriented fork could switch to
  float32 (checkpoints already round-trip through float32) for roughly 2x
  throughput.
