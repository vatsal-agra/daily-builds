# Sprout — a tiny LLM, grown from scratch

## Concept

Every other "from scratch" build in this repo has been a classical algorithm
(SAT solvers, path tracers, a chess engine, a SQL database, a compression
toolkit...). Today's build tackles the thing that defines this era of
software instead: a **decoder-only transformer language model**, trained
from raw text, with every piece of math implemented by hand.

No PyTorch. No TensorFlow. No JAX. No autograd library (that's cheating —
and it's also literally a different project already in this repo,
`2026-06-16-cotangent`, which built a generic reverse-mode AD engine).
Sprout instead hand-derives the **forward AND backward pass** for every
layer of a GPT-style transformer — embeddings, causal multi-head
self-attention, layer norm, GELU feed-forward, cross-entropy loss — as
explicit NumPy matrix algebra, verified against numerical gradients before
a single real training run happens. Then it trains a real (tiny) model on
a real (small, original) text corpus and generates real completions.

## Why this is interesting

- It's the one artifact type this repo hasn't built: a generative model,
  not a solver or a renderer.
- Manual backprop through multi-head attention is genuinely fiddly (three
  separate head-split/merge reshapes, a softmax that needs the Jacobian
  trick, residual streams that need gradients summed not overwritten) —
  getting it right, and *proving* it's right with gradient checks, is the
  meat of the engineering.
- It's honest about scale: this is not a chatbot. It's a ~200K-parameter
  model trained for a few minutes on CPU on ~150KB of original text. The
  point is to watch it visibly climb from "random noise" to "recognizable
  word shapes and sentence rhythm" — and to be able to open the hood and
  see exactly why, token by token, layer by layer.

## Architecture

```
raw text corpus (data/corpus.txt, original, written for this project)
        │
        ▼
   BPE tokenizer (train merges, encode/decode)  — tokenizer.py
        │  token ids
        ▼
┌───────────────────────────────────────────────┐
│  GPT-style decoder-only transformer  (nn.py)   │
│                                                 │
│  token embed[id] + positional embed[pos]       │
│        │                                       │
│  ┌─► LayerNorm ─► Causal MultiHeadAttention ──►(+residual)
│  │        │                                    │
│  │  LayerNorm ─► Linear→GELU→Linear (FFN) ────►(+residual)
│  │                                              │
│  └── repeat × N layers ──────────────────────┘  │
│        │                                       │
│  final LayerNorm ─► output projection ─► logits│
└───────────────────────────────────────────────┘
        │
        ▼  cross-entropy loss vs next-token target
   manual backward() ─► grads for every parameter
        │
        ▼
   Adam optimizer (optim.py, from scratch) updates weights
        │
        ▼
   sampling: temperature / top-k / top-p  (generate.py)
        │
        ▼
   CLI chat + a tiny HTTP playground (server.py) +
   attention-heatmap HTML visualizer
```

Every `Module` in `nn.py` (Linear, LayerNorm, Embedding, CausalSelfAttention,
MLP, Block, GPT) implements `forward(x)` (caching what backward needs) and
`backward(dout)` (returning dx, accumulating parameter grads in `self.grads`).
`gradcheck.py` perturbs each parameter by ±ε and compares the numerical
slope to the analytic gradient before training is trusted.

## Feature list

**Required (4):**
1. **BPE tokenizer** — trains byte-pair-encoding merges from the corpus,
   encodes/decodes text ↔ token ids, saves/loads vocab+merges as JSON.
2. **Transformer forward + backward from scratch** — full GPT-style
   decoder stack (embeddings, causal multi-head self-attention, layer
   norm, GELU MLP, residuals, weight init) with hand-written backward pass
   for every op, correctness proven by numerical gradient checking.
3. **Training loop** — Adam optimizer from scratch, minibatching over the
   token stream, gradient clipping, train/val loss tracking, checkpoint
   save/load (so training can resume), periodic sample generation during
   training so progress is visible.
4. **Text generation** — autoregressive sampling with temperature, top-k,
   and top-p (nucleus) filtering; an interactive CLI completion/chat mode
   that loads a checkpoint and generates from a user prompt.

**Stretch (2+):**
5. **Attention visualizer** — a self-contained interactive HTML page that
   runs a prompt through the trained model and renders per-layer,
   per-head attention weight heatmaps over the actual tokens.
6. **Web playground + model card** — a zero-dependency `http.server`
   playground (type a prompt, get a live completion, same "server holds
   the real logic" pattern as this repo's Gambit/Formulate builds) plus an
   auto-generated model card (param count, corpus stats, final
   train/val loss & perplexity, sample generations at each training
   checkpoint) so the model's actual capability is documented honestly.

## Non-goals

- No pretrained weights, no internet-downloaded corpus (everything is
  written for this project — avoids licensing questions and network
  dependence).
- No GPU/CUDA — pure NumPy, CPU only, sized to actually finish training in
  this session.
- Not attempting real language competence — a few-hundred-thousand
  parameter model trained on ~150KB of text will produce locally coherent
  but globally silly text. That's the honest, expected outcome and the
  README will say so plainly.
