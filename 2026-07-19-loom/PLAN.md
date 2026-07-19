# Loom — a transformer language model built from first principles

## Concept

Every ML-adjacent build in this repo so far has stayed at the "classical
algorithm" layer (Cotangent's scalar autodiff MLP, QSim's quantum circuits,
VecNN's HNSW). None of them tackle the architecture that actually eats the
world right now: the Transformer. **Loom** is a decoder-only GPT-style
language model — token embeddings, learned positions, multi-head causal
self-attention, layernorm, residual streams, a feedforward block, and a
softmax cross-entropy training loop — built entirely on a **from-scratch
reverse-mode tensor autodiff engine** (no PyTorch/TensorFlow/JAX/autograd of
any kind). Every gradient the model uses is computed by backprop code we
wrote and verified ourselves against numerical finite differences.

Why it's interesting:
- It's the one big idea in modern computing that this ledger hasn't touched.
- It forces getting reverse-mode autodiff right for *matrices*, not scalars
  (Cotangent already proved scalar autodiff works here — this is the harder,
  more valuable next step: broadcasting, matmul backprop, softmax/layernorm
  Jacobians, attention masking).
- It composes naturally with this repo's existing verification culture:
  every op gets gradient-checked, every training run gets a loss curve that
  must actually go down, and the "does it work" bar is "generates
  recognizable words and phrases from a from-scratch model," not a vibe.

## Architecture

```
loom/
  tensor.py       - Tensor class: numpy-backed, reverse-mode autodiff graph
                    (add/sub/mul/div/matmul/transpose/reshape/sum/mean/exp/
                    log/pow/relu/gelu/softmax/layernorm/embedding-lookup/
                    masked_fill/concat/split), broadcasting-aware backward.
  nn.py           - Linear, Embedding, LayerNorm, MultiHeadAttention (causal),
                    FeedForward, TransformerBlock, GPT model, CrossEntropyLoss.
  optim.py        - Adam optimizer + LR warmup/cosine decay + grad clipping,
                    built directly on Tensor.grad (no framework).
  tokenizer.py    - CharTokenizer (baseline) + from-scratch BPE tokenizer
                    (merge-pair training loop, encode/decode round-trip).
  data.py         - Corpus loader + sliding-window batch sampler.
  train.py        - Training loop: forward -> loss -> backward -> Adam step;
                    checkpointing (npz), loss logging.
  generate.py     - Autoregressive sampling: temperature, top-k, top-p (nucleus).
  gradcheck.py    - Central finite-difference checker for every autodiff op
                    and for the full model end-to-end.
  cli.py          - `loom` CLI: train/generate/gradcheck/tokenize/attn/demo.
corpus/
  loom_corpus.txt - Original, hand-authored training corpus (own prose).
viz/
  attention.html  - Self-contained interactive attention-heatmap visualizer
                    (per-layer, per-head, step-through generation).
tests/
  test_*.py       - unittest suite.
demo.sh
README.md
```

## Feature list

**Required (core, must work end-to-end, no stubs):**

1. **Tensor autodiff engine** — numpy-backed `Tensor` with a real
   computation graph and reverse-mode `.backward()`, supporting broadcasting,
   matmul, softmax, layernorm, and all ops the model needs. Verified with
   central finite-difference gradient checks against every single op (not
   just the composed model).
2. **GPT-style transformer built on the engine** — token + positional
   embeddings, N transformer blocks (multi-head causal self-attention +
   residual + pre-norm LayerNorm, feedforward + residual + pre-norm
   LayerNorm), final projection to vocab logits. No borrowed framework code
   anywhere in the forward or backward pass.
3. **Training pipeline** — Adam optimizer (bias-corrected), LR warmup +
   cosine decay, gradient clipping, minibatched sliding-window sampling over
   an original hand-authored corpus, checkpoint save/load. Gate: loss
   demonstrably drops from ~ln(vocab) (random-init) to a much lower value
   over training, and the trained model's samples contain real recognizable
   words, not noise.
4. **Sampling / generation CLI** — autoregressive generation with
   temperature, top-k, and top-p (nucleus) sampling from a trained
   checkpoint, given an arbitrary text prompt.

**Stretch:**

5. **Interactive HTML attention visualizer** — self-contained page (no
   external deps) that replays a real generation run and renders the actual
   per-layer, per-head attention-weight matrices as heatmaps over the token
   sequence, with step-through/play controls.
6. **From-scratch byte-pair-encoding (BPE) tokenizer** — trains merge rules
   directly from the corpus (no `tiktoken`/`sentencepiece`), with an
   encode/decode round-trip that's verified lossless, usable as a drop-in
   alternative to the char-level tokenizer.

## Verification philosophy (matches this repo's track record)

- Every autodiff op gradient-checked against numerical finite differences
  (this caught real bugs in Cotangent and will here too — matmul/softmax/
  layernorm backprop are exactly the kind of code that's subtly wrong until
  proven otherwise).
- End-to-end model gradient check: perturb a real weight inside a real
  forward pass through the full transformer and confirm analytic vs.
  numerical gradient agree to ~1e-4 relative error.
- A training run is not "done" until loss goes down by a large, logged
  margin and generated samples are inspected for real words/structure.
