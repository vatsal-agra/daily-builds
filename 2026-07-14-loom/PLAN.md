# Loom — a transformer language model, built from scratch

## Concept

Every previous daily build that touched machine learning stopped at either a
generic autodiff engine + MLP (Cotangent, 2026-06-16) or classical algorithms
(SAT, ray tracing, vector search). None of the 40+ prior builds implement the
architecture actually underneath every modern LLM: a decoder-only Transformer,
trained with real backpropagation, from raw bytes of text to sampled tokens.

**Loom** is a GPT-style causal transformer language model implemented entirely
in NumPy (array math only — no PyTorch, TensorFlow, JAX, or autograd library
of any kind). It trains a byte-pair-encoding tokenizer from scratch, builds a
small transformer stack (token+positional embeddings → N × [causal multi-head
self-attention → feed-forward, both pre-norm + residual] → output head),
computes every gradient by hand via manual backpropagation (verified against
numerical finite-difference gradients — the same rigor Cotangent applied to
its scalar autodiff engine, now applied to matrix ops: embeddings, attention
softmax, layer norm, GELU), trains with Adam + LR warmup/cosine decay on a
real text corpus until loss visibly falls and generations stop being random
noise, and samples new text autoregressively with temperature/top-k/top-p.

## Why this is interesting

- It's the one major "how do LLMs actually work" question this project
  hasn't answered yet, despite the daily-build prompt explicitly suggesting
  "a tiny LLM" as an option.
- Backprop through attention (softmax Jacobian, QKV projections, multi-head
  reshape/concat) is a genuinely different — and harder — gradient-checking
  problem than the scalar-DAG autodiff Cotangent built. Doing it with raw
  matrix calculus (no `.backward()` from a library) is the whole point.
- It's small enough to train to a legible result on a CPU in a few minutes
  (tiny d_model, 2 layers, short context, a few thousand steps) while still
  being the real architecture, not a toy simplification of it.

## Architecture

```
raw text corpus
      │
      ▼
BPE tokenizer (trained from scratch: byte-level base vocab + learned merges)
      │  encode → token ids
      ▼
Embedding: token_emb[id] + pos_emb[position]           (NumPy arrays, no lib)
      │
      ▼
┌─────────────────── N × TransformerBlock ───────────────────┐
│  x = x + CausalSelfAttention(LayerNorm(x))                  │
│  x = x + FeedForward(LayerNorm(x))    (GELU, 4x expansion)  │
└──────────────────────────────────────────────────────────────┘
      │
      ▼
Final LayerNorm → output head (weight-tied to token embedding) → logits
      │
      ▼
softmax cross-entropy loss  ◄── training
   OR
temperature / top-k / top-p sampling  ◄── generation
```

Every arrow above is implemented with an explicit `forward()` that caches
what it needs, and an explicit `backward(grad_out)` that computes the exact
analytic gradient — a hand-rolled reverse-mode differentiation of one fixed
computational graph, not a generic autodiff tape. Correctness is proven by
comparing every module's analytic gradient against a central finite-difference
numerical gradient over random inputs.

## Feature list

**Required (core, must work end-to-end):**
1. **BPE tokenizer trained from scratch** — byte-level base alphabet + greedy
   pair-merge learning over a real corpus, with encode/decode that round-trips
   arbitrary text (including bytes outside the training corpus) exactly.
2. **Transformer decoder architecture in raw NumPy** — embeddings, causal
   multi-head self-attention, pre-norm residual blocks, GELU feed-forward,
   final layer norm, weight-tied output head. Configurable depth/width/heads.
3. **Hand-written backpropagation through the entire stack**, gradient-checked
   module-by-module against numerical (finite-difference) gradients on random
   inputs, tight enough to prove there is no library autodiff hiding underneath.
4. **Training loop that demonstrably learns** — minibatched cross-entropy
   loss, Adam optimizer, LR warmup + cosine decay, gradient clipping,
   checkpoint save/load, on a real text corpus, with loss falling from
   near-random (~ln(vocab)) to meaningfully lower, and generations visibly
   improving from noise to structured text.

**Stretch:**
5. **Autoregressive sampling CLI** — temperature, top-k, and top-p (nucleus)
   sampling, plus a REPL-style "complete this prompt" chat mode against a
   trained checkpoint.
6. **Interactive HTML visualizer** — per-layer, per-head attention heatmaps
   for a given prompt (which tokens attend to which), plus a live loss-curve
   chart rendered from the training log — both self-contained, no server.

## Corpus & scale (kept CPU-trainable in minutes, not hours)

Small public-domain text corpus (a few hundred KB), small BPE vocab
(~500–1000 tokens), tiny model (d_model≈128, 4 heads, 2–4 layers, context
≈128 tokens) — enough to be the real architecture and show real learning,
not so big that training exceeds a CPU budget of a few minutes.

## Verification plan

- Gradient-check every module (embedding, linear/matmul, layer norm, softmax
  attention, GELU, cross-entropy) against finite differences.
- Train-loss regression test: loss after N steps must be below a fixed
  threshold measurably lower than the loss at step 0.
- Tokenizer round-trip fuzz test over random byte strings.
- `demo.sh` running tokenizer train → gradcheck → train → sample → viz,
  asserting output at each stage.
