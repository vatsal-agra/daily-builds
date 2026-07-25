# Loom — a GPT-style Transformer language model, built from scratch

## Concept

Every "from scratch" build in this repo so far has reimplemented a classic
algorithm — SAT solvers, VCS, compression, ray tracers, a spreadsheet engine.
None has touched the thing currently reshaping software: the decoder-only
Transformer that powers every modern LLM. **Loom** is a from-scratch GPT —
tokenizer, self-attention, backpropagation, and the Adam training loop —
implemented with nothing but Python + NumPy (NumPy supplies matrix multiply
and elementwise ops only; no autograd, no `torch`, no `jax`, no `transformers`).
Every gradient is derived by hand and checked against finite differences,
the same rigor this repo's autodiff build (Cotangent) applied to a scalar
`Value` DAG — except here the object being differentiated is a full
multi-head-attention transformer block.

## Why this is interesting

- It is the one foundational-CS idea conspicuously missing from the ledger.
- "Attention" is genuinely a *loom*: it weaves a new representation of each
  token by taking a weighted combination of every other token's value
  vector, with weights computed from query/key dot products. The name and
  the visualizer (a literal thread-weight heatmap per head) follow directly
  from the math.
- Manually deriving backprop through softmax-attention, LayerNorm, and a
  GELU MLP — then verifying it numerically — is a serious test of "did you
  actually understand it, or did you just call `.backward()`."
- Training data: rather than depend on network access (blocked for
  arbitrary hosts in this sandbox) or risk mis-transcribing a real public
  domain text from memory, the corpus is an **original, procedurally
  generated corpus of fables** ("The Loom Fables") — clearly synthetic,
  license-clean, and its low-entropy, repetitive structure is exactly what
  lets a tiny (CPU-only, few-minute-training) model produce genuinely
  coherent output instead of gibberish. This is an honest engineering
  choice, called out explicitly rather than hidden.

## Architecture

```
2026-07-25-loom/
  corpus/
    make_corpus.py      # procedural generator -> fables.txt (original text)
    fables.txt           # generated training corpus
  loom/
    tokenizer.py         # from-scratch byte-level BPE: train, encode, decode
    tensor_ops.py         # numpy-backed primitives + finite-diff grad checker
    layers.py            # Embedding, LayerNorm, Linear, MHA, MLP — each with
                          # manual forward() AND backward()
    model.py             # GPT: stack of blocks, causal mask, tied output head
    optimizer.py          # Adam + weight decay, grad clipping, warmup+cosine LR
    train.py              # training loop, checkpointing, loss logging
    generate.py           # autoregressive sampling: temperature/top-k/top-p,
                          # plus a KV-cache fast path
    cli.py                # `loom train|generate|gradcheck|viz|demo`
  viz/
    visualizer.html       # self-contained: attention heatmaps per layer/head
                          # + step-through generation viewer (loads a JSON
                          # trace exported by the CLI; no server needed)
  tests/
    test_gradcheck.py     # numerical vs analytic gradients, every layer
    test_tokenizer.py     # BPE round-trip, merge determinism
    test_model.py         # shape checks, causal-mask leakage check, overfit-
                          # one-batch sanity check
    test_generate.py      # sampling determinism under seed, KV-cache parity
  demo.sh                 # trains a real model, generates samples, exports
                          # a visualizer trace, runs the full test suite
  checkpoints/            # saved trained model (weights + tokenizer)
  README.md
  PLAN.md / REVIEW.md
```

## Feature list

**Required (4) — must work end-to-end, no stubs:**

1. **From-scratch byte-level BPE tokenizer.** Trains merge rules directly
   off the corpus (no external tokenizer library), encodes/decodes with an
   exact round trip, deterministic given the same corpus.
2. **From-scratch Transformer forward + backward pass.** Multi-head causal
   self-attention, LayerNorm, GELU feed-forward, residual connections,
   weight-tied output projection — every layer's `backward()` is derived by
   hand and verified against numerical (central finite-difference)
   gradients to a tight tolerance.
3. **Real training loop.** Adam optimizer (bias-corrected, weight decay),
   gradient clipping, LR warmup + cosine decay, minibatching over the
   tokenized corpus — loss must demonstrably fall over training and be
   logged/plottable, on an actual training run (not a canned loss curve).
4. **Autoregressive generation with temperature / top-k / top-p sampling.**
   Given a prompt, samples continuations from the trained model; output
   quality is judged against the model's own training corpus style.

**Stretch (2+):**

5. **KV-cache generation.** A second generation path that caches per-layer
   key/value projections so each new token costs O(1) attention work
   instead of O(n); benchmarked against the naive path to show the speedup,
   with an exact-output-parity check (cached vs uncached must generate
   identical tokens for the same seed).
6. **Interactive HTML attention visualizer.** Self-contained page loading a
   JSON trace: per-layer/per-head attention-weight heatmaps over an input
   string, plus a step-through view of next-token probability distributions
   during generation.

## Verification strategy

- Gradient correctness is the crux of the whole project: `tests/test_gradcheck.py`
  perturbs every parameter tensor by ±ε and compares to the analytic
  gradient from `backward()`, for every layer type, at random inputs.
- `demo.sh` runs a real training job end to end (not mocked), so the loss
  curve and sample generations in the README are from an actual run anyone
  can reproduce.
