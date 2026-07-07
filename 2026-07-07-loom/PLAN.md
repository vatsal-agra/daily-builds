# Loom — a tiny LLM built from scratch

## Concept

Every LLM you can `pip install` hides three things behind a `.fit()` call:
a tensor autograd engine, a tokenizer, and a Transformer. Loom builds all
three from first principles — no PyTorch, no TensorFlow, no JAX, no
`transformers`, no autograd library. Just NumPy arrays for storage/BLAS
matmul, and hand-written reverse-mode automatic differentiation driving a
real decoder-only Transformer that trains on real text (Tiny Shakespeare,
~1.1MB, public domain) and actually gets better at predicting it.

"From scratch" here means: every gradient in the system is produced by a
computational graph *we* built and traced, not by calling into someone
else's autodiff. NumPy is used only as a fast array/BLAS substrate (the
same role C would play) — never as a source of pre-built ML primitives.

## Why it's interesting

The daily-build history for this repo is full of "from scratch" builds —
SAT solvers, VCS systems, path tracers, crypto suites, a spreadsheet — but
never the thing that arguably matters most in 2026: the actual mechanism
powering an LLM. Building a real autograd engine is a different kind of
"from scratch" than re-implementing a well-known deterministic algorithm:
correctness is adversarial by nature (a subtly wrong backward pass doesn't
crash, it just quietly fails to learn), which makes gradient checking and
an "overfit a tiny batch to ~0 loss" test the real proof of correctness —
much closer to how real ML infra is verified.

## Architecture

```
loom/
  tensor.py     — Tensor: numpy ndarray + autograd (add/mul/matmul/pow/
                  exp/log/sum/mean/reshape/transpose/getitem/concat,
                  broadcasting-aware backward, topological-sort backward()).
  functional.py — softmax, log_softmax, cross_entropy, layer_norm, gelu,
                  causal self-attention — all composed from Tensor ops
                  (so their gradients come from the engine, not hand-coded).
  nn.py         — Linear, Embedding, LayerNorm, MultiHeadAttention,
                  TransformerBlock, GPT (token+pos embed, N blocks, tied
                  output head), Module base class (parameters(), state_dict).
  optim.py      — Adam from scratch (bias-corrected moments), cosine LR
                  schedule with linear warmup, gradient clipping.
  tokenizer.py  — byte-level BPE: trains merges from corpus statistics,
                  encode/decode over raw UTF-8 bytes (so any Unicode text
                  round-trips exactly, never an <unk>).
  data.py       — corpus loading, train/val split, random batch sampler
                  over token id sequences.
  train.py      — training loop: forward → cross-entropy → backward →
                  Adam step, periodic val loss, checkpoint save/load
                  (JSON + .npz), loss history.
  generate.py   — autoregressive sampling: greedy, temperature, top-k,
                  top-p (nucleus); a REPL-style completion CLI.
  viz.py        — renders a self-contained interactive HTML page: live
                  attention-head heatmaps for a chosen prompt, the
                  training loss/perplexity curve, and a from-scratch PCA
                  projection of the learned token embedding space.
  cli.py        — `loom` entry point: tokenizer / train / generate / chat
                  / viz / test / demo subcommands.
data/
  tinyshakespeare.txt — training corpus (public domain, Andrej Karpathy's
                        char-rnn dataset mirror).
tests/          — gradient checks, tokenizer round-trip, causal-mask
                  leakage test, tiny-batch overfit test, full mini
                  training run, generation sanity, CLI smoke tests.
```

## Feature list

**Required (must fully work end-to-end):**

1. **Autograd engine** — a `Tensor` class with reverse-mode automatic
   differentiation over NumPy arrays (broadcasting-correct gradients for
   add/mul/matmul/pow/exp/log/sum/reshape/transpose/slicing/concat).
   Verified with finite-difference numerical gradient checking on random
   tensors for every op, including a chained multi-op graph.

2. **Byte-level BPE tokenizer** — trained from scratch on the corpus
   (frequency-ranked pair merging, configurable vocab size), with
   `encode`/`decode` that exactly round-trip arbitrary text (including
   Unicode/punctuation never seen at train time, since it falls back to
   raw bytes). Saved/loaded as JSON.

3. **Decoder-only Transformer (GPT-style) architecture** — token +
   learned positional embeddings, N pre-norm blocks (causal multi-head
   self-attention + GELU MLP + residual connections), final LayerNorm,
   weight-tied output projection — built entirely as compositions of
   `Tensor` ops, so its backward pass is 100% engine-derived, not
   hand-written per layer.

4. **Real training pipeline** — from-scratch Adam optimizer + LR warmup/
   cosine decay + gradient clipping, cross-entropy loss, minibatch
   sampling over the tokenized corpus, checkpointing. Gate: training loss
   and held-out validation perplexity measurably and monotonically(-ish)
   improve over a real run on Tiny Shakespeare, and the trained model's
   sample completions are qualitatively better than an untrained model's
   (real learned structure: word boundaries, capitalization after
   newlines, character names, etc. — not memorized/hardcoded strings).

**Stretch (implement at least 1):**

5. **Sampling strategies + interactive completion CLI** — greedy,
   temperature, top-k, and top-p (nucleus) sampling, plus a `loom chat`
   REPL that completes whatever prompt the user types using the trained
   checkpoint.

6. **Interactive HTML visualizer** — a single self-contained page showing
   (a) per-head causal attention-weight heatmaps for a live prompt run
   through the actual trained model, (b) the real training loss/val-
   perplexity curve, and (c) a from-scratch 2D PCA projection of the
   learned token embedding table.

## Verification strategy

Because a broken autograd/Transformer implementation *looks* like it
works (it runs, it doesn't crash, loss is a number) while being totally
wrong, the two load-bearing tests are:

- **Gradient checking**: every autograd op's analytic gradient compared
  against central-difference numerical gradients on random inputs.
- **Overfit test**: the full model, trained on a single small fixed
  batch for enough steps, must drive loss to near-zero (near-perfect
  next-token prediction on that batch) — the standard ML-engineering
  proof that forward + backward + optimizer are all wired correctly
  together, independent of whether the model *generalizes*.

On top of those: a causal-mask leakage test (position *i*'s output must
be provably invariant to changes at positions > *i*), tokenizer
round-trip fuzzing, and an end-to-end scripted training + generation run.
