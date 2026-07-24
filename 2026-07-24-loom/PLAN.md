# Loom — a tiny GPT-style language model, built from scratch

## Concept

Every prior daily build that touched "intelligence" reached for something
adjacent to ML (vector search / HNSW in VecNN, computer vision in Optic) but
none has built the thing everyone means when they say "AI" today: an
autoregressive transformer language model, trained end-to-end from raw text
to producing new text. Loom is that — not a wrapper around PyTorch, but a
from-scratch reverse-mode automatic differentiation engine (a tensor-valued
micrograd), a byte-pair-encoding tokenizer trained from scratch on a real
corpus, a GPT-2-style decoder-only transformer built entirely out of that
autodiff engine's primitives, and an Adam optimizer — trained on the public
domain "Tiny Shakespeare" corpus until it produces genuinely novel,
recognizably Shakespeare-flavored text.

## Why it's interesting

- It's the one category of "from scratch" build this repo hasn't attempted:
  every op (matmul, softmax, layernorm, embedding lookup, cross-entropy) has
  to carry its own backward pass, hand-derived, or the model never learns
  anything and the whole thing is theater.
- It is falsifiable in a way that's fun to watch: a broken backward pass
  doesn't crash, it just fails to learn — loss stays flat. The bug surface
  is "quietly wrong gradients," which is exactly why Phase 5 includes
  numerical gradient checking (finite-difference vs. analytic) as a hard
  correctness gate, not just an integration smoke test.
- It's genuinely useful as a teaching artifact: with model dims small enough
  to train on a CPU in minutes, someone can read every line of the forward
  pass and know precisely what a transformer does, with an attention-weight
  visualizer to make the mechanism visible rather than a black box.

## Architecture

```
data/shakespeare.txt          Tiny Shakespeare corpus (public domain, ~1.1MB)
        |
        v
tokenizer.py    BPE tokenizer: trained from scratch on the corpus
        |         (byte-level, merge-pair learning, encode/decode, JSON vocab save/load)
        v
engine.py       Tensor: numpy-backed value + autograd tape
        |         ops: +, -, *, matmul, transpose, reshape/view, sum, mean,
        |         exp, log, pow, relu, gelu, softmax (log-sum-exp stable),
        |         layernorm, embedding-lookup, dropout, cross-entropy
        v
model.py        GPT: token + positional embedding -> N x TransformerBlock
        |         (causal multi-head self-attention, residual, LayerNorm,
        |         2-layer GELU MLP, residual) -> final LayerNorm -> LM head
        v
optim.py        Adam optimizer (bias-corrected moments) over Tensor.grad
        v
train.py        Batches random windows from the corpus, forward -> loss ->
        |         backward -> step, periodic checkpoint (npz) + sample
        |         generation + loss-curve logging (JSON)
        v
generate.py     Autoregressive sampling: temperature / top-k / top-p,
        |         KV-free full-recompute (model is tiny, this is fine)
        v
server.py       stdlib http.server backend: /generate, /attention,
        |         /status (training-loss history), serves static/
        v
static/         Single-page HTML/CSS/JS UI: chat-style generation panel,
                  attention-heatmap viewer (per layer/head), training-loss
                  chart, all vanilla JS/Canvas, no CDN/build step
```

No PyTorch/TensorFlow/JAX/scikit-learn/transformers/tinygrad — the only
third-party dependency is NumPy, used purely as a fast ndarray + BLAS matmul
substrate (the same pattern this repo already uses in Flux and VecNN).
Every gradient is hand-derived and lives in `engine.py`.

## Feature list

1. **[required] From-scratch reverse-mode autodiff engine** (`engine.py`) —
   a `Tensor` class wrapping a numpy array, building a dynamic computation
   graph via closures captured on each op, with a topological-sort
   `.backward()`. Verified by finite-difference gradient checking against
   every op, not just tested via "the model eventually trains."

2. **[required] From-scratch BPE tokenizer** (`tokenizer.py`) — starts from
   raw bytes, greedily merges the most frequent adjacent pair for a
   configurable number of merges, producing a vocab substantially smaller
   than character-level while still handling arbitrary unseen text (falls
   back to byte tokens, so it can never hit an unknown-token error).

3. **[required] GPT-style decoder-only transformer trained on real text**
   (`model.py` + `train.py`) — causal multi-head self-attention, learned
   positional embeddings, pre-LN transformer blocks, GELU MLP, weight-tied
   or separate LM head, trained with Adam + cross-entropy on Tiny
   Shakespeare until validation loss demonstrably drops from
   random-init (~ln(vocab_size)) to a meaningfully lower plateau, with a
   saved checkpoint anyone can load and generate from without retraining.

4. **[required] Autoregressive text generation with real sampling
   strategies** (`generate.py`) — temperature scaling, top-k, and top-p
   (nucleus) sampling, all implemented from scratch on the raw logit
   tensor (no `numpy.random.choice`-does-everything shortcut hiding the
   math), runnable both from a CLI and from the web UI.

5. **[stretch] Interactive web UI** (`server.py` + `static/`) — a
   self-contained page (chat-style prompt -> generation, adjustable
   temperature/top-k/top-p/length) backed by a real stdlib HTTP server
   calling the actual loaded model — same pattern as Formulate's
   server-backed spreadsheet, zero model logic duplicated in JS.

6. **[stretch] Attention visualization** — an endpoint + UI panel that
   runs a prompt through the trained model and renders the real per-head,
   per-layer attention-weight matrices as heatmaps, so the mechanism is
   inspectable rather than a black box.

## Success criteria (what makes this "done", not "basically works")

- Numerical gradient check passes for every autodiff op to a tight
  tolerance — this is the actual correctness gate for the hardest part
  of the system.
- Training loss on Tiny Shakespeare drops from near `ln(vocab_size)`
  (random-guess baseline) to a clearly lower, plateauing value, logged
  and checked programmatically, not eyeballed once.
- Generated text, sampled from the trained checkpoint, is not gibberish:
  it should show real word structure, Shakespeare-flavored vocabulary,
  and script-like formatting (character names, line breaks) — checked by
  an automated heuristic in the test suite (real-word ratio, non-trivial
  entropy) plus a printed sample for human inspection in demo.sh.
- The UI and attention visualizer actually round-trip through the trained
  checkpoint over real HTTP calls, not mocked responses.
