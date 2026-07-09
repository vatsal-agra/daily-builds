# Loom — a tiny language model, built from scratch

## Concept

Everything between "matrix multiply" and "the model wrote a sentence" is
usually a black box: PyTorch's autograd, `nn.MultiheadAttention`, `torch.optim.Adam`.
Loom rebuilds that whole stack by hand — a reverse-mode autograd `Tensor`
engine (NumPy for raw array math only, zero ML libraries), a GPT-style
decoder-only Transformer built directly on top of it, a from-scratch Adam
optimizer, a training loop, and nucleus/top-k sampling — then trains a real
character-level language model on a bundled corpus and generates new text
from it. It closes the loop from "here is a matrix" to "here is a model
that writes sentences it was never shown," which is the most interesting
and least-transparent piece of modern software.

This is a deliberate escalation from a prior build in this repo (Cotangent,
2026-06-16), which was scalar-graph autodiff powering a small MLP classifier.
Loom is tensor-shaped autograd (broadcasting, matmul, reductions) powering a
real attention-based sequence model trained with a real optimizer — a
different point in the design space, not a rerun.

## Why it's interesting

- Autograd over *tensors* (not scalars) is a different, harder problem:
  broadcasting has to be undone correctly on the backward pass or gradients
  silently have the wrong shape and the whole system is quietly wrong.
- Attention is the mechanism everyone's downstream tools are named after and
  almost nobody has hand-derived the backward pass for. Building it exposes
  exactly why causal masking, softmax stability, and multi-head reshaping
  are each their own small trap.
- A trained model is falsifiable in a way most from-scratch systems aren't:
  either the loss goes down and it generates plausible text, or it doesn't.
  There's no partial credit for "the math looks right."

## Architecture

```
corpus/*.txt                  original bundled text corpora (public-domain-
                               style prose I wrote myself, no scraped data)
        │
   tokenizer.py                char-level vocab (encode/decode)
        │
   tensor.py                   Tensor: numpy ndarray + autograd graph
                               (add/mul/matmul/pow/exp/log/sum/mean/
                                reshape/transpose/gather/concat/softmax/
                                broadcasting-correct backward)
        │
   nn.py                       Linear, Embedding, LayerNorm, GELU,
                               CausalSelfAttention (multi-head), MLP,
                               TransformerBlock, GPT (embed → N blocks →
                               final LN → tied output head)
        │
   optim.py                    Adam from scratch (moment estimates, bias
                               correction, weight decay, grad clipping)
        │
   train.py     ──────────►    training loop: batches, cross-entropy loss,
        │                      LR warmup+cosine decay, checkpointing,
        │                      loss-curve JSON log
        │
   generate.py                 autoregressive sampling: greedy / temperature
                               / top-k / nucleus (top-p), interactive chat
        │
   attention_trace.py          forward pass that also records every head's
                               attention-weight matrix for a given prompt
        │
   viz/attention.html          self-contained interactive visualizer:
                               per-layer/per-head attention heatmaps over
                               real tokens + live training loss curve
        │
   loom.py                     CLI: gradcheck / train / generate / chat /
                               viz / demo
```

No PyTorch, TensorFlow, JAX, or any autograd/ML library anywhere in the
stack. NumPy is used strictly as a raw array/BLAS library — every gradient
is derived and coded by hand in `tensor.py`.

## Feature list

**Required:**
1. **Tensor autograd engine** (`tensor.py`) — dynamic computational graph
   over NumPy arrays with correct broadcasting-aware backward for every op
   (add, mul, matmul, pow, exp, log, sum, mean, reshape, transpose, gather,
   concat, masked-fill, softmax, layernorm), verified against numerical
   (finite-difference) gradients.
2. **GPT-style Transformer from scratch** (`nn.py`) — token + positional
   embeddings, causal multi-head self-attention, GELU MLP, pre-LN residual
   blocks, weight-tied output head — built entirely out of `Tensor` ops,
   with a working, checked backward pass through the whole model.
3. **From-scratch training pipeline** (`optim.py` + `train.py`) — hand-coded
   Adam optimizer, cross-entropy loss, gradient clipping, LR warmup+cosine
   schedule, minibatching over a real bundled text corpus, checkpoint
   save/load, and a loss curve that demonstrably decreases.
4. **Text generation** (`generate.py`) — autoregressive sampling with
   temperature, top-k, and nucleus (top-p) filtering, plus an interactive
   CLI chat/completion mode running the trained model live.

**Stretch:**
5. **Interactive attention visualizer** (`viz/attention.html`) — feed it any
   prompt, see every layer's every head's real attention-weight heatmap
   over the actual tokens, plus the real training loss curve, in a
   self-contained HTML page (no server, no external deps).
6. **Configurable model sizes + checkpointing** — a `--preset` flag
   (tiny/small/base) trading depth/width/context for speed, with
   save/load round-tripping to bit-identical logits, so a trained model
   can be shipped and reloaded without retraining.

## Corpus

Bundled corpora are original text I write for this project (not scraped),
so there are no licensing questions: a short fantasy-chronicle narrative
with recurring characters/place names (so a tiny char-level model has
real structure to learn — names, quotes, sentence rhythm) and a smaller
plain-prose sample for fast smoke tests.
