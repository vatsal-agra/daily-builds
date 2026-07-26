# Loom — a tiny transformer language model, built from scratch

## Concept

Loom is a decoder-only transformer language model — the same architecture
family as GPT — implemented from first principles with **no ML framework**
(no PyTorch, no TensorFlow, no JAX, no `autograd`/`torch.nn`). Every piece
that a framework normally gives you for free is hand-built here:

- a **byte-pair-encoding tokenizer** trained from scratch on a real corpus
- a **reverse-mode automatic-differentiation engine over NumPy tensors**
  (not scalars — this has to be fast enough to actually train a multi-layer
  attention model), including matmul, broadcasting, softmax, layernorm and
  embedding-lookup backward rules
- the **transformer architecture itself** — token+positional embeddings,
  causal multi-head self-attention, feed-forward blocks, residual
  connections, layer norm — composed purely from the autograd engine's
  primitive ops, the same way you'd compose it in real PyTorch `nn.Module`
  code, except every `backward()` is ours
- a **training loop** (cross-entropy loss, Adam optimizer, LR warmup+decay,
  minibatching) that trains the model on a real text corpus until it
  visibly learns (loss drops, samples go from noise to structure)
- **autoregressive text generation** with temperature / top-k / top-p
  sampling

## Why it's interesting

Every other "from scratch, no deps" build in this repo has picked a classical
algorithm (SAT solvers, ray tracers, VCS, databases, compression). A
transformer LM is the defining algorithm of the current moment, and building
one bottom-up — starting from "what even is a gradient" and ending with a
model that writes plausible next tokens — is the single best way to show
genuine understanding rather than API familiarity. It's also a serious
engineering test: unlike Cotangent's earlier scalar-value autodiff graph
(fine for toy MLPs), a transformer needs *tensor-shaped* autodiff with
correct broadcasting/matmul/reduction backward rules, or training a batch
would take forever. Getting that right, and getting attention right, is
where the real bugs live — exactly the kind of adversarial-review bait this
routine is designed to catch.

## Architecture

```
text corpus
   │
   ▼
tokenizer.py        BPE: train (byte-pairs merges) → encode/decode
   │
   ▼  token ids
autograd.py          Tensor class: numpy ndarray + autograd tape
                      ops: add, mul, matmul, transpose, reshape, slice,
                      softmax, layernorm, embedding-gather, GELU, sum/mean,
                      cross-entropy — every op registers a backward closure
   │
   ▼
model.py              LoomModel: embedding → N × TransformerBlock → 
                       (causal multi-head attention, feed-forward, 
                        pre-LN residual) → output projection
   │
   ▼
train.py              Adam optimizer (from scratch: m/v moments, bias
                       correction), LR warmup+cosine decay, minibatch
                       sampler, checkpoint save/load (JSON + npz-like
                       binary weight format written by hand)
   │
   ▼
generate.py            autoregressive sampling loop: temperature, top-k,
                        top-p (nucleus), optional KV-cache for speed
   │
   ▼
server.py + playground.html   http.server backend exposing
                       /generate and /attention endpoints; browser UI
                       streams tokens and renders live attention heatmaps
                       (same "browser holds zero model logic, every request
                       is a round trip to the real Python engine" pattern
                       as Gambit's chess board and Formulate's spreadsheet)
```

## Feature list

### Required (4)
1. **From-scratch BPE tokenizer** — trained on the bundled corpus (byte-level
   merges up to a configurable vocab size), with `encode`/`decode` that
   round-trip losslessly, saved/loadable vocab+merges file.
2. **Tensor autograd engine** — a `Tensor` class wrapping NumPy arrays with
   a backward tape; implements every op the transformer needs (matmul,
   broadcasting add/mul, transpose/reshape, softmax, layernorm, GELU,
   embedding gather, cross-entropy) with **gradient-checked** backward rules
   (verified against numerical finite-difference gradients in the test
   suite — this is the correctness bar, not "it ran without crashing").
3. **Transformer model + training loop** — multi-head causal self-attention,
   feed-forward blocks, residual + pre-LN, tied/untied output head, built
   entirely on the autograd engine; Adam optimizer from scratch; trains on
   a real corpus with measurably decreasing loss and improving generated
   samples over the course of training.
4. **Autoregressive generation** — temperature, top-k, and top-p (nucleus)
   sampling from the trained model, with a CLI to prompt it and get
   continuations.

### Stretch (2+)
5. **KV-cache generation** — incremental decoding that caches past
   key/value tensors instead of recomputing the full sequence's attention
   every step, benchmarked against the naive version to show the speedup.
6. **Interactive server-backed playground** — a browser UI (styled, not
   default) that POSTs a prompt to a real Python `http.server` running the
   trained model, streams the generated continuation, and renders a live
   per-layer, per-head **attention heatmap** for the generated tokens, plus
   a training-loss-curve view.

## Corpus

Bundled: a public-domain text corpus checked into the project (a curated
subset of Project Gutenberg text — small enough to train a tiny model on
CPU in a few minutes, large enough to show the model learning real
character/word statistics, spelling, and rudimentary structure). Corpus
license/source noted in README.

## Success bar

- Autograd backward passes match numerical gradients to float32 tolerance
  for every op, checked in the test suite.
- Training loss visibly and monotonically-on-average decreases across an
  epoch; a full run-log is saved and checked into the repo as evidence.
- Generated samples after training are visibly more structured (real words,
  plausible bigrams) than samples from an untrained model with the same
  architecture.
- `demo.sh` trains a small model from nothing, generates from it, and hits
  every CLI/server code path with zero manual steps.
