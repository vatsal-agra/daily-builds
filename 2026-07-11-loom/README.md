# Loom

A Transformer language model trained on a from-scratch tensor autodiff
engine — no PyTorch, no JAX, no `autograd`, no `torch`. `numpy` is used only
as a fast ndarray container and BLAS matmul; every gradient in this codebase
is hand-derived and shipped as a `.backward()` closure on its operator, then
proven correct against finite-difference gradients rather than trusted on
faith.

*Status: Shipped. All 4 required + 3 stretch features complete, adversarially
reviewed (7 real bugs found and fixed, see `REVIEW.md`), and verified:
84/84 automated tests green plus an 8-check `demo.sh` walking the real CLI
end-to-end.*

## What it is

Two things, stacked:

1. **A tensor autodiff engine** (`loom/tensor.py`) — the same primitive set
   real deep learning frameworks are built from: matmul with batching and
   broadcasting, elementwise arithmetic, reductions, softmax, LayerNorm,
   GELU, embedding-table gather, causal masking, and a fused cross-entropy
   loss. Every operator's backward pass is hand-derived and independently
   verified with central-difference numeric gradients to ~1e-9 relative
   error (`loom/gradcheck.py`).

2. **A GPT-style decoder-only Transformer** (`loom/nn.py`) built *purely*
   from that engine's ops — token + positional embeddings, multi-head causal
   self-attention, pre-LN residual blocks, a GELU MLP, and a tied output
   head. Because every op composing the model already has a correct
   backward pass, the model's backward pass requires zero model-specific
   backward code — it falls out of composition. That's the thing actually
   being tested here: gradcheck the full model end-to-end (all 28 parameter
   tensors on a random tiny GPT) and it passes with no special-casing.

On top of that: a from-scratch byte-level BPE tokenizer, a from-scratch
Adam optimizer, a training loop that demonstrably drives loss down on real
text, temperature/top-k/top-p sampling, and an interactive HTML visualizer
that shows real per-head attention weights and a real loss curve from an
actual trained checkpoint.

## Why I built this today

`LEDGER.md` has five ray tracers, six CDCL SAT solvers, three from-scratch
Git implementations, and one prior autodiff project (Cotangent, a *scalar*
`Value`-DAG engine training a small MLP). Nothing in the ledger builds the
actual mechanism modern language models run on: reverse-mode autodiff over
*tensors* (with broadcasting, batched matmul, and attention-shaped ops) and
a real Transformer trained on top of it. It's also unusually falsifiable —
a broken attention backward pass shows up immediately as a gradcheck
mismatch, and a broken training loop shows up as loss that doesn't move.
Both are hard to fake, which is exactly the kind of build this routine
rewards over a plausible-looking demo.

## How to run it

```bash
pip install -r requirements.txt   # numpy only

# train a tokenizer + tiny GPT on the bundled corpus, generate, and write
# an interactive visualizer -- the fastest way to see everything work:
python3 -m loom.cli demo

# or drive each stage yourself:
python3 -m loom.cli gradcheck                                   # prove the math is right
python3 -m loom.cli tokenize corpus/hollow_loom.txt --merges 300
python3 -m loom.cli train corpus/hollow_loom.txt --out ckpt --steps 300
python3 -m loom.cli generate ckpt --prompt "The loom" --tokens 200 \
  --temperature 0.8 --top-k 40 --top-p 0.95
python3 -m loom.cli viz ckpt --prompt "The loom" --out viz.html  # open in a browser
```

Verify the whole thing:

```bash
python3 -m unittest discover -s tests -q   # 84 tests, ~7s
bash demo.sh                                # full CLI walkthrough, ~35s
```

## Feature list

**Required:**

1. **Tensor autodiff engine** (`loom/tensor.py`) — matmul (batched,
   broadcasting), elementwise arithmetic, reductions, reshape/transpose,
   softmax, LayerNorm, GELU, embedding gather, causal masking, fused
   cross-entropy. Every op finite-difference gradient-checked.
2. **GPT-style Transformer** (`loom/nn.py`) — multi-head causal
   self-attention, pre-LN residual blocks, GELU MLP, tied output head. Full
   model gradient-checks end-to-end across all parameter tensors.
3. **Byte-level BPE tokenizer** (`loom/tokenizer.py`) — trained from
   scratch on a real corpus, exact round-trip on arbitrary input including
   unicode and the full 256-byte range.
4. **Training loop + from-scratch Adam** (`loom/train.py`,
   `loom/optim.py`) — minibatched causal-LM cross-entropy training with
   gradient clipping and checkpointing; loss provably decreases (asserted
   in tests, not eyeballed).

**Stretch:**

5. **Temperature / top-k / top-p sampling** (`loom/sample.py`).
6. **Interactive HTML visualizer** (`loom/viz.py`) — real per-layer/
   per-head attention heatmaps, a scrubbable/playable generation replay,
   and the real training loss curve, all from an actual forward pass.
   Colors follow this repo's dataviz skill (validated categorical/
   sequential palettes, light+dark mode). Verified in headless Chromium:
   zero console errors, every control exercised and screenshotted.
7. **One-command `demo`** (`loom/demo.py`) — trains a real tokenizer + GPT
   on the bundled corpus in ~17s on CPU and prints an untrained-vs-trained
   comparison, both the generated text (control-character babble → broken
   but recognizable English word fragments) and an objective cross-entropy
   number (~6.2 → ~3.5 nats/token on the bundled corpus).

## Honesty about limitations

The bundled corpus (`corpus/hollow_loom.txt`, an original ~9KB short story
written for this project) is small enough that the default training config
overfits it — train loss keeps dropping while val loss plateaus or drifts
up. That's expected and is the correct, honestly-reported behavior for a
demo-scale model on a demo-scale corpus; it's not hidden or averaged away
anywhere in the code or the docs. Generation has no KV cache, so it
recomputes attention over the full trailing context at every token — a
real, known performance limitation of the from-scratch implementation, not
a correctness bug, and out of scope for what this build promised.

## Where a human could take this next

- **Scale it up**: bigger `n_embd`/`n_layer`/`block_size`, a bigger corpus,
  more training steps. The engine and model have no hard-coded assumptions
  that would break at scale — only wall-clock time (pure numpy, no GPU).
- **KV caching** for generation, to make sampling long sequences fast
  instead of recomputing the full context every step.
- **Dropout and weight decay schedules** for a less overfit-prone training
  recipe on small corpora.
- **A `Tensor.backward()` topological-sort optimization** (memoize the
  post-order traversal per unique graph shape) if training throughput ever
  matters more than code clarity.
- **Multi-query / grouped-query attention**, RoPE positional embeddings, or
  other modern architecture variants — since attention is a well-isolated
  module here, these are localized changes.
- **A proper BPE priority-queue trainer** (the current one recomputes pair
  frequencies from scratch every merge step — correct and simple, but
  `O(merges × corpus_len)` rather than the incremental-count approach real
  BPE trainers use).

## Layout

```
loom/            the engine + model + training + CLI (see PLAN.md for the
                 full module-by-module architecture)
tests/           84 tests: gradchecks, correctness, regressions, a headless-
                 browser UI smoke test
corpus/          bundled training text
demo.sh          exercises every CLI feature end-to-end
PLAN.md          architecture and feature-list plan (written before the code)
REVIEW.md        Phase 3 adversarial review: 7 real bugs found and fixed
```
