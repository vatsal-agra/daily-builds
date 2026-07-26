# Loom — a tiny GPT-style language model, built from scratch

## Concept

Every previous "from scratch" build in this ledger has picked one classical
system (a renderer, a SAT solver, a database, a VCS, a chess engine, a
compression codec, a scalar autodiff + MLP...) and implemented it down to
first principles. Nothing so far has built the thing that defines this era
of computing: a Transformer language model. Loom is a decoder-only,
GPT-style LLM — tokenizer, transformer architecture, backpropagation, and
optimizer — implemented with nothing but NumPy array math (no PyTorch, no
JAX, no autograd library, no `.backward()` from a framework).

Two things make this a genuine "from scratch" build rather than "call
`torch.nn.TransformerDecoder`":

1. **A hand-rolled tensor autodiff engine.** Every operator the model uses
   (matmul, add, layer norm, softmax, GELU, embedding gather, cross-entropy)
   is a node in a small computation graph with its own forward *and*
   backward rule, verified against numerical (finite-difference) gradients
   — the same rigor Cotangent (2026-06-16) applied to scalar autodiff, now
   applied to batched tensor ops so a real multi-head attention Transformer
   can be trained end-to-end.
2. **A hand-rolled byte-pair-encoding tokenizer**, trained on the model's
   own corpus rather than borrowing a pretrained vocabulary.

## Why this is interesting

- It's the mathematically richest thing in the ledger to derive by hand:
  the backward pass through softmax attention, LayerNorm, and GELU each
  require real matrix calculus (not just chain-ruling scalar multiplies).
- It closes the loop from "autodiff exists" (Cotangent) to "autodiff trains
  the architecture that matters right now."
- It's honestly scoped: a nanoGPT-sized model (tens of thousands of
  parameters, character/BPE-level, CPU-only, a few minutes of training) —
  the point is a *correct, complete, inspectable* pipeline, not a
  state-of-the-art model. Every gate below is about correctness and
  completeness, not about producing Shakespeare-quality prose.

## Architecture

```
raw corpus (data/corpus.txt, original text authored for this build)
        │
        ▼
  BPE tokenizer (loom/tokenizer.py)         — trained from scratch on the corpus
        │  encode() → token ids
        ▼
  Tensor autodiff engine (loom/tensor.py)   — Tensor node + forward/backward per op
        │
        ▼
  GPT model (loom/model.py)
    token embedding + learned positional embedding
    → N × TransformerBlock:
         LayerNorm → causal multi-head self-attention → residual
         LayerNorm → MLP (Linear → GELU → Linear)      → residual
    → final LayerNorm → linear head → logits over vocab
        │
        ▼
  Adam optimizer + LR schedule (loom/optim.py)
        │
        ▼
  Training loop (loom/train.py) — cross-entropy loss, checkpointing
        │
        ▼
  Sampling (loom/generate.py) — greedy / temperature / top-k / top-p
        │
        ▼
  Attention visualizer (loom/attn_viz.py) → self-contained HTML/SVG
```

CLI entry point: `loom.py` (subcommands: `train-tokenizer`, `train`,
`generate`, `chat`, `attn-viz`, `gradcheck`, `demo`).

## Feature list

**Required (must fully work end-to-end, no stubs):**

1. **Byte-level BPE tokenizer trained from scratch** — merge-pair counting,
   iterative merging to a target vocab size, `encode`/`decode` that
   round-trip exactly, vocab+merges persisted to disk and reloadable.
2. **Tensor autodiff engine + GPT transformer forward pass** — a `Tensor`
   class wrapping NumPy arrays that builds a computation graph; ops needed
   for a real Transformer (matmul, add/broadcast, transpose/reshape,
   softmax, layernorm, GELU, embedding gather, cross-entropy) each with a
   correct `backward`, gradient-checked against finite differences.
3. **End-to-end training loop** — Adam optimizer (bias-corrected moments),
   LR warmup + cosine decay, gradient clipping, batched next-token
   cross-entropy training over the corpus, with training loss measurably
   decreasing and checkpoint save/load.
4. **Autoregressive text generation** — greedy, temperature, top-k, and
   top-p (nucleus) sampling from a trained checkpoint, exposed through a
   CLI `generate` command and an interactive `chat` REPL.

**Stretch (2+, ship at least 1):**

5. **Interactive attention visualizer** — runs a real forward pass on a
   user-supplied prompt and renders the *actual* per-layer, per-head
   attention weight matrices as an interactive self-contained HTML/SVG
   heatmap (layer/head picker, hover-to-inspect token pair weights) — no
   fabricated data.
6. **Gradient-check CLI + test suite** — `loom gradcheck` runs numerical
   vs. analytic gradient comparison across every op and through a full
   mini forward+backward pass of the whole model, printing max relative
   error per op.
7. **Loss-curve + sample-quality report** — an HTML/SVG training report
   (loss curve over steps, sample generations at several checkpoints
   during training) so training progress is inspectable, not just a
   terminal log.

## Honesty note on scale

This is a nanoGPT-scale model (small `d_model`, few layers/heads, short
context, a purpose-written multi-thousand-word original corpus) that trains
in minutes on CPU-only NumPy. The goal is a **complete, correct, from-scratch
pipeline** — tokenizer → autodiff → transformer → optimizer → sampler —
not a large or fluent model. README and REVIEW will state measured
loss/perplexity and show real (not cherry-picked) sample output.
