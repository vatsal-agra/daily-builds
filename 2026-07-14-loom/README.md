# Loom

A GPT-style transformer language model, built entirely from scratch in
NumPy — tokenizer, architecture, backpropagation, training, and sampling,
all hand-written, with **no PyTorch, TensorFlow, JAX, or autodiff library
of any kind.**

## What it is

Loom takes raw text all the way to a working, generating language model:

1. A **byte-level BPE tokenizer**, trained from scratch (greedy pair-merge
   learning over a real corpus), that round-trips any text — including
   text it never saw during training — exactly.
2. A **GPT-style decoder-only transformer** in raw NumPy: token + positional
   embeddings, N layers of pre-norm causal multi-head self-attention +
   GELU feed-forward with residual connections, a final layer norm, and a
   weight-tied output head.
3. **Hand-written backpropagation** through every one of those ops —
   embeddings, linear layers, layer norm, the softmax-attention Jacobian,
   GELU's exact derivative, fused softmax-cross-entropy — proven correct by
   comparing each analytic gradient against a finite-difference numerical
   gradient (not just "it looks right": `python3 cli.py gradcheck` actually
   checks it, every time).
4. A real **training loop** — Adam, LR warmup + cosine decay, gradient-norm
   clipping, checkpointing — that visibly drives loss down from
   near-random on a bundled Shakespeare corpus.
5. **Autoregressive sampling** with temperature, top-k, and top-p (nucleus)
   filtering.
6. A **self-contained interactive HTML visualizer** — no server — showing
   per-layer/per-head attention heatmaps (hover for the exact weight) and
   the training loss curve, both theme-aware (light/dark).

## Why this one, today

Reading `LEDGER.md`, every previous daily build that touched machine
learning stopped at either a generic scalar autodiff engine + MLP
(Cotangent) or classical, non-ML algorithms (SAT solvers, ray tracers,
vector search, physics engines, a compiler, a database...). None of the
40+ prior builds implement the architecture actually underneath every
current LLM — and the daily-build prompt explicitly lists "a tiny LLM" as
a suggestion. Backprop through attention (the softmax Jacobian, QKV
projections, multi-head reshape/merge) is also a genuinely different and
harder matrix-calculus problem than a scalar computation-graph autodiff,
so it exercises muscle the repo hadn't used yet.

## How to run it

```bash
pip install -r requirements.txt   # just numpy

# prove the hand-written backprop is analytically correct
python3 cli.py gradcheck

# train a tiny model on the bundled Shakespeare corpus (~45s on CPU)
python3 cli.py train --out runs/demo --vocab-size 384 --d-model 64 \
  --n-heads 4 --n-layers 2 --seq-len 64 --batch-size 24 --steps 300 \
  --lr 3e-3 --warmup 30

# generate text from the trained checkpoint
python3 cli.py sample --run runs/demo --prompt "ROMEO:" --temperature 0.8 --top-k 40

# render the interactive attention/loss visualizer (open the .html in a browser)
python3 cli.py viz --run runs/demo --prompt "ROMEO: what light"

# or run the whole pipeline (train -> gradcheck -> sample -> viz) at once
python3 cli.py demo

# run the full verification suite (unit tests + 23-check CLI walkthrough)
python3 -m unittest discover -s tests
./demo.sh
```

For a more capable (and much slower — tens of minutes on CPU) model, use
the `train` defaults: `python3 cli.py train --steps 2000` (vocab 512,
d_model 128, 4 layers, seq_len 128).

**Honest expectation-setting:** the demo-scale config above (2 layers,
d_model=64, 300 steps) learns the corpus's *structure* — character-name
lines, dialogue formatting, colons, capitalization — but not real English
words yet at that tiny scale/step count. That's an accurate, unfiltered
example, not a cherry-picked longer run (see REVIEW.md for why that
distinction mattered here). Training longer / bigger closes the gap; this
repo just doesn't spend the CPU-hours to prove it in `demo.sh`.

## Full feature list

**Required (all 4 shipped, working end-to-end):**
- Byte-level BPE tokenizer trained from scratch with lossless round-trip
  (`loom/tokenizer.py`)
- Transformer decoder architecture in raw NumPy: causal multi-head
  attention, pre-norm residual blocks, GELU feed-forward, weight-tied
  output head (`loom/nn.py`, `loom/model.py`)
- Hand-written backpropagation for every op, gradient-checked against
  finite differences across depths, batch sizes, and edge cases
  (seq_len=1, batch=1) (`loom/gradcheck.py`)
- Adam + warmup/cosine-decay training loop with grad clipping and
  checkpointing that demonstrably drives loss down on real text
  (`loom/optim.py`, `loom/train.py`)

**Stretch (both shipped):**
- Temperature / top-k / top-p (nucleus) autoregressive sampling CLI
  (`loom/sample.py`)
- Interactive, self-contained, light/dark-theme-aware HTML visualizer:
  sequential-blue attention heatmaps with a legend and hover tooltips
  (exact weight + both token labels), and a training-loss line chart with
  a hover crosshair and direct end-label (`loom/viz.py`)

**Process artifacts:**
- `PLAN.md` — architecture and feature plan written before implementation
- `REVIEW.md` — adversarial review: 6 real bugs found (a visualizer crash,
  an unescaped-`</script>` injection gap, raw tracebacks leaking on bad
  input, a missing-directory crash, a code-quality shortcut, and a
  test-coverage gap) with repro steps and fixes
- `tests/` — 55 unit tests, all green
- `demo.sh` — 23-check end-to-end verification through the real CLI

## Where a human could take this next

- **Scale it up.** The architecture is real; it's just small. A bigger
  d_model/context/corpus (plus, realistically, a faster backend —
  vectorized NumPy on CPU is the bottleneck long before the architecture
  is) would close the "structure but not real words" gap noted above.
- **KV caching.** Generation currently re-runs the full forward pass for
  every new token; caching past keys/values would make sampling
  near-linear instead of quadratic in generation length.
- **Resume training from a checkpoint.** Right now `train` always starts
  fresh; the checkpoint format supports resuming, but the optimizer state
  (Adam's moment estimates) isn't currently persisted alongside it.
- **RoPE or ALiBi** instead of learned absolute positional embeddings,
  for better length generalization beyond the trained context window.
- **A real evaluation harness** — held-out perplexity, not just training
  loss — to separate "memorizing the training set" from "generalizing."
