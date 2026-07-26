# Loom

## Concept

A GPT-style decoder-only Transformer language model, built entirely from
scratch: its own reverse-mode autograd tensor engine (no PyTorch, TensorFlow,
JAX, or scikit-learn — NumPy is used only as a dense-array/BLAS backend, the
same way earlier daily builds used it for math, not for framework logic),
its own byte-pair-encoding tokenizer trained from raw text, its own
multi-head causal self-attention and training loop (Adam, LR warmup+decay,
gradient clipping), and an interactive HTML visualizer that shows the real
attention weights of the real trained model as it generates text token by
token.

## Why this is interesting

Every daily build so far that touched "from scratch" territory has picked
classical algorithms — SAT solvers, ray tracers, VCS, compilers, crypto,
compression, chess. None has built the architecture behind modern LLMs. The
interesting part isn't "call an API" — it's proving every gradient by hand:
implementing backprop through softmax, layer normalization, multi-head
attention, and embedding lookups as *primitive tensor operations* with
verified backward passes (checked against numerical finite-difference
gradients, the same way a real ML framework's test suite works), then
watching a from-scratch training loop actually reduce loss and produce
generated text that reflects the training corpus. It closes the loop from
"autodiff engine" (Cotangent, a prior build, did scalar autodiff for an MLP)
up to "the actual Transformer architecture that GPT/Claude/etc. are built
on," at toy scale but with zero hand-waving in the math.

## Architecture

```
loom/
  tensor.py     — Tensor class: numpy-backed autograd engine.
                  Primitive ops: add, sub, mul, div, matmul, transpose,
                  reshape, sum, mean, exp, log, sqrt, pow, softmax,
                  embedding-lookup, cross-entropy. Each op stores a
                  backward closure; Tensor.backward() does reverse
                  topological-order accumulation. Broadcasting handled
                  via an "unbroadcast" reduction in each op's backward.
  nn.py         — Modules built from tensor.py primitives only:
                  Embedding, LayerNorm (composed from primitives, so its
                  backward is free/automatic), CausalSelfAttention
                  (multi-head, causal mask, scaled dot-product), MLP
                  (GELU), Block (pre-norm residual x2), GPT (stack of
                  Blocks + final LN + weight-tied LM head).
  optim.py      — Adam optimizer (bias-corrected) + LR warmup/cosine
                  decay + global-norm gradient clipping, all hand-written.
  tokenizer.py  — Byte-level BPE: trains merges from corpus statistics,
                  encode/decode, round-trip verified on arbitrary text
                  including unicode.
  data/corpus.txt — an original (not copied) ~85 KB text corpus written
                  for this project so training data has no license/
                  accuracy concerns.
  train.py      — batches the corpus, runs the training loop, logs loss,
                  checkpoints weights (npz) + tokenizer merges (json).
  generate.py   — loads a checkpoint, autoregressive sampling
                  (temperature + top-k), optional KV-cache for speed.
  viz.py        — renders a self-contained interactive HTML page that
                  replays a real generation: per-layer per-head attention
                  heatmaps over the actual token stream, scrubbable.
cli.py          — `train / generate / chat / tokenize / gradcheck /
                  viz / demo` subcommands.
tests/          — unit tests (gradient checks per op, attention causality,
                  tokenizer round-trip, LN statistics) + an integration
                  test that trains a tiny model and asserts loss drops.
demo.sh         — exercises every feature end-to-end from a clean clone.
```

## Feature list

**Required (core, must fully work end-to-end):**
1. **From-scratch autograd tensor engine** — every primitive op's backward
   pass verified against numerical (finite-difference) gradients, including
   through broadcasting, matmul, and softmax.
2. **GPT-style Transformer architecture** — token + positional embeddings,
   multi-head causal self-attention (causal mask verified: changing a future
   token never changes an earlier position's output), pre-norm residual
   blocks, GELU MLP, weight-tied output head.
3. **From-scratch byte-level BPE tokenizer** — trained from real corpus
   statistics (not hardcoded merges), encode/decode round-trips exactly on
   arbitrary text including unicode and text never seen during training.
4. **Real training loop that reduces loss** — Adam + LR schedule + grad
   clipping, minibatched over an original corpus, checkpointed, with
   autoregressive generation (temperature/top-k sampling) from the trained
   model producing text that's recognizably shaped by the corpus (not
   random noise, not the corpus copy-pasted).

**Stretch (2+):**
5. **Interactive HTML attention visualizer** — replays a real generation
   from the trained checkpoint; per-layer, per-head attention-weight
   heatmaps over the actual token sequence, scrubbable/steppable.
6. **KV-cache** for O(1)-per-token incremental generation instead of
   recomputing the full sequence at every step (a real perf optimization,
   verified to produce numerically identical logits to the non-cached path).
7. **Interactive `chat` REPL** — loads a checkpoint and streams generated
   tokens live as you type a prompt.

## Non-goals

Not aiming for anything resembling production LLM scale or quality — this
is a toy model (thousands, not billions, of parameters) meant to prove the
architecture and math are real and correct, trained on a small original
corpus on CPU in minutes.
