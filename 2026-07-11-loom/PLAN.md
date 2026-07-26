# Loom — a Transformer language model built on a from-scratch tensor autodiff engine

## Concept

Every prior deep-learning-adjacent build in this ledger (Cotangent, 2026-06-16)
implemented reverse-mode autodiff over *scalars* (a `Value` DAG, one float per
node) and trained a small MLP. Loom goes one level up the stack: a reverse-mode
autodiff engine over *numpy tensors* (matmul, broadcasting, reductions,
softmax, layernorm, GELU, embedding gather — the actual primitive set modern
deep learning frameworks are built from), and on top of that engine, a real
GPT-style decoder-only Transformer, trained end-to-end on real text with a
from-scratch byte-pair-encoding tokenizer and a from-scratch Adam optimizer.

Nothing in this build imports PyTorch/JAX/TensorFlow/autograd/torch. `numpy`
is used purely as a fast array container + BLAS matmul — every gradient path
is hand-derived and shipped as a `.backward()` closure on the op, then proven
correct by finite-difference gradient checking (the same verification
discipline Cotangent used for its scalar engine, extended to tensors with
broadcasting, attention masks, and reshapes — a strictly harder correctness
problem, since a single tensor gradient bug silently corrupts an entire
layer instead of one scalar).

## Why this is interesting

- It's the one clearly-uncovered corner of "from scratch, verified against
  ground truth" in this ledger: every other from-scratch-algorithm build
  (SAT, ray tracing, VCS, compression, crypto, DB, physics) has multiple
  entries; nothing here builds the actual mechanism (attention +
  backprop-through-a-DAG-of-tensors) that GPT-style models run on.
- Correctness is unusually falsifiable: a broken attention backward pass or a
  broken softmax gradient shows up immediately as a finite-difference
  mismatch, and a broken model shows up as loss that doesn't decrease. Both
  are hard to fake, which is exactly the kind of build this routine rewards.
- It's a genuine "from math to product": start from the chain rule, end with
  a program that visibly gets better at predicting the next byte of real
  text, sampled live with temperature/top-k/top-p, with attention weights
  you can literally look at in a browser.

## Architecture

```
loom/
  tensor.py        # Tensor: numpy ndarray + autograd (matmul, +, -, *, /, **,
                    #  sum, mean, transpose, reshape, exp, log, tanh, relu,
                    #  softmax, masked_fill, embedding gather, broadcasting-
                    #  aware backward via topological sort + grad accumulation)
  nn.py             # Linear, LayerNorm, GELU, CausalSelfAttention (multi-head,
                    #  causal mask), MLP block, Embedding, GPT (full model:
                    #  tok+pos embed -> N transformer blocks -> final LN ->
                    #  output head, weight-tied to tok embedding)
  optim.py          # Adam from scratch (bias-corrected moments, per-param state)
  tokenizer.py      # Byte-level BPE: trains merges on a corpus, encode/decode,
                    #  round-trip-safe on arbitrary bytes (GPT-2-style approach)
  data.py           # Corpus loading, batching (random contiguous chunks),
                    #  train/val split
  train.py          # Training loop: forward -> loss -> backward -> Adam step,
                    #  gradient clipping, checkpoint save/load (json + npz),
                    #  loss-curve logging
  sample.py         # Autoregressive generation: temperature, top-k, top-p
                    #  (nucleus) sampling, from a trained checkpoint
  gradcheck.py      # Finite-difference gradient checker, run over every op
                    #  in tensor.py and over the full model end-to-end
  viz.py            # Exports real forward-pass data (attention weights per
                    #  layer/head, generation trace, loss curve) to JSON and
                    #  renders a self-contained interactive HTML visualizer
  cli.py            # `loom train / generate / gradcheck / tokenize / viz /
                    #  demo` entry point
tests/
  test_tensor.py    # unit + finite-difference checks for every autodiff op
  test_nn.py        # shape/gradient checks for LayerNorm, attention (incl.
                    #  causal-mask correctness), MLP, full GPT forward+backward
  test_tokenizer.py # BPE round-trip (incl. random bytes, empty input, unicode),
                    #  determinism, merge-count behavior
  test_optim.py     # Adam converges on a toy convex quadratic
  test_train.py     # end-to-end: a few training steps strictly decrease loss
  test_e2e.py       # full pipeline smoke test: train tiny BPE -> train tiny
                    #  GPT for N steps -> generate -> checkpoint round-trip
demo.sh             # exercises every CLI subcommand end-to-end, asserts on
                    #  output, fails loudly on any error
corpus/             # bundled public-domain-ish training text (small, so the
                    #  demo trains in well under a minute on CPU)
README.md
PLAN.md / REVIEW.md
```

## Feature list

**Required (must work end-to-end, no stubs):**

1. **Tensor autodiff engine** (`tensor.py`) — reverse-mode autograd over numpy
   arrays: matmul (with broadcasting over batch dims), elementwise arithmetic,
   reductions (sum/mean over arbitrary axes), reshape/transpose, softmax,
   layernorm, GELU, embedding-table gather, causal masking. Verified with
   finite-difference gradient checks on every single operator (not just the
   model as a whole) — this is the foundation everything else sits on.

2. **GPT-style Transformer** (`nn.py`) — token + learned positional
   embeddings, N pre-LN transformer blocks (multi-head causal self-attention
   + residual, LayerNorm, GELU MLP + residual), final LayerNorm, output head
   tied to the token embedding. Multi-head attention implemented as real
   Q/K/V projections, scaled dot-product scores, causal mask, softmax,
   weighted value sum, output projection — built purely from `tensor.py` ops
   so its backward pass comes for free from the engine and is itself
   gradient-checked layer by layer and end-to-end.

3. **Byte-level BPE tokenizer** (`tokenizer.py`) — trains merge rules on a
   real corpus from scratch (byte-pair frequency counting + iterative
   merging, GPT-2's approach), encodes/decodes any input including bytes
   outside the training corpus, with an exact round-trip guarantee.

4. **Training loop with a from-scratch Adam optimizer** (`train.py`,
   `optim.py`) — minibatched causal-LM cross-entropy training with gradient
   clipping, bias-corrected Adam updates, checkpoint save/load, and a loss
   curve that demonstrably decreases on a real training corpus (verified in
   tests, not eyeballed).

**Stretch (2+):**

5. **Sampling strategies** (`sample.py`) — temperature scaling, top-k, and
   top-p (nucleus) sampling for autoregressive generation from a trained
   checkpoint, exposed via CLI flags.

6. **Interactive HTML visualizer** (`viz.py`) — a self-contained page showing
   real per-layer/per-head attention-weight heatmaps for a given prompt
   (data exported from an actual forward pass, not fabricated), a
   token-by-token generation replay, and the real training loss curve.

7. **One-command `demo`** — trains a real (tiny) tokenizer + model on a
   bundled corpus in well under a minute on CPU, then generates and shows
   visibly-improved text quality compared to an untrained model, proving the
   entire pipeline is real and not a fixed/mocked output.

## Gates

- Every autodiff op passes finite-difference gradient checking to at least
  1e-4 relative error.
- The full GPT model passes an end-to-end finite-difference gradient check
  (loss gradient w.r.t. every parameter tensor, on a tiny random model).
- Training loss strictly decreases over a fixed number of steps on a fixed
  seed (asserted in a test, not just observed).
- BPE tokenizer round-trips arbitrary byte strings, including edge cases
  (empty string, single byte, all-256-byte-values string).
- `demo.sh` runs the entire pipeline (tokenize -> gradcheck -> train ->
  generate -> viz) and exits 0.
