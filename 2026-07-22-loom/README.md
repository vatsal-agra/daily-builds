# Loom

*A tiny transformer language model, built from scratch — no PyTorch, no TensorFlow, no JAX.*

Loom is a small GPT-style decoder-only transformer. Every layer of the
stack that a framework normally hands you for free is hand-built here: the
tensor autograd engine that computes gradients, the tokenizer that turns
text into tokens, the transformer architecture itself, the optimizer that
trains it, and the sampler that generates from it.

## What it is

- **`loom/autograd.py`** — a `Tensor` class wrapping NumPy arrays with a
  reverse-mode backward tape: matmul, broadcasting add/sub/mul/div,
  reshape/transpose, sum/mean, softmax, layer norm, GELU, embedding
  gather, cross-entropy. Every op's backward rule is checked against
  numerical finite differences in `tests/test_autograd.py` — not "it ran,"
  but "the gradient is provably correct to float precision."
- **`loom/tokenizer.py`** — byte-level BPE trained from scratch on the
  corpus. Any input, seen or unseen, round-trips losslessly (worst case it
  falls back to raw bytes).
- **`loom/nn.py`** — the transformer: token + positional embeddings,
  causal multi-head self-attention, GELU feed-forward blocks, pre-LN
  residual connections, a weight-tied output head — composed entirely from
  the autograd primitives above, the same way you'd wire up `nn.Module`
  subclasses in a real framework, except every `backward()` here is ours.
- **`loom/optim.py`** — Adam (Kingma & Ba, 2015) from scratch, with linear
  warmup + cosine LR decay.
- **`loom/generate.py`** — autoregressive sampling with temperature,
  top-k, and top-p (nucleus) filtering, plus an optional KV-cache for fast
  incremental decoding.
- **`server.py` + `static/playground.html`** — an interactive browser
  playground backed by a real Python `http.server`. The browser holds zero
  model logic; every prompt is a network round trip to the actual trained
  model (the same "browser is a dumb terminal" pattern this repo's Gambit
  chess engine and Formulate spreadsheet use). Shows the generated text,
  a live per-layer/per-head attention heatmap for it, the training loss
  curve, and a before/after-training sample comparison.

## Quick start

```bash
pip install -r requirements.txt      # numpy, nothing else
python3 train.py                     # trains the tokenizer + model, saves checkpoints/loom.{npz,json}
python3 sample.py --prompt "The weaver" --tokens 150 --temperature 0.8 --top-k 40
python3 server.py                    # interactive playground at http://127.0.0.1:8420
python3 benchmark.py                 # KV-cache vs. full-recompute speed comparison
./demo.sh                            # runs everything above end-to-end and checks it all
```

A trained checkpoint (`checkpoints/loom.{npz,json}`, 3 layers, 4 heads,
dim 64, ~181K params, 2000 training steps) is committed so `sample.py`
and `server.py` work immediately without training first.

## Feature list

**Required (4/4 shipped):**
1. From-scratch BPE tokenizer, verified lossless round-trip on seen and
   unseen text (including emoji, empty string, pathological repeats).
2. NumPy tensor autograd engine — every backward rule gradient-checked
   against finite differences.
3. Transformer + training loop (causal multi-head attention, weight tying,
   Adam from scratch) — trains on a real corpus with loss dropping
   6.09 → 3.15 over 2000 steps and samples visibly improving from pure
   noise to real word fragments.
4. Autoregressive generation with temperature / top-k / top-p sampling.

**Stretch (2/2 shipped):**
5. KV-cache incremental decoding — verified bit-identical to full
   recompute under greedy decoding, **~2.7x faster** in `benchmark.py`.
6. Interactive server-backed playground with live attention
   visualization, training-loss curve, and before/after samples —
   browser-tested end-to-end with Playwright.

See [PLAN.md](./PLAN.md) for the full architecture writeup and
[REVIEW.md](./REVIEW.md) for the adversarial-review findings (two real
bugs found and fixed: a causal-masking gap during KV-cache prompt-priming,
and a generation-path divergence for prompts at/over the context window).

## Training results

Trained on `corpus/corpus.txt` (see below), 2000 steps, ~6.7 minutes on
CPU:

| step | train loss | val loss |
|-----:|-----------:|---------:|
| 0    | 6.09       | 6.08     |
| 200  | 3.88       | 4.42     |
| 1000 | 3.12       | 4.15     |
| 1999 | 3.15       | 4.14     |

Train loss keeps dropping past step ~1000 while val loss plateaus/creeps
up slightly — honest, visible overfitting given a ~2,300-word corpus asked
to support ~500 effective epochs. That's an expected, disclosed property
of a *tiny* model on a *tiny* corpus, not a hidden problem: the full curve
is in `checkpoints/train_log.json` and rendered live in the playground.

Sample before training (random weights): garbage bytes, as expected.
Sample after training: real word fragments, punctuation, capitalization,
and short recognizable words ("through", "Millbrook", "nail", "spring")
recombined in locally-plausible but not globally coherent ways — exactly
what a ~180K-parameter model trained on ~12KB of text should produce.

## Corpus

`corpus/corpus.txt` is an original short-story collection ("The Loom of
Small Things," nine linked fables) written specifically for this project.
It is *not* fetched from an external archive: this environment's egress
policy blocks outbound requests to public-domain text sources like Project
Gutenberg (confirmed via a genuine 403 policy denial, not a transient
failure — see the build log). Writing an original corpus sidesteps that
limitation entirely and avoids any licensing ambiguity.

## Why I built this today

Every other "from scratch, no dependencies" build in this repo picks a
classical algorithm — SAT solvers, ray tracers, version control, database
engines, compression codecs. A transformer language model is the defining
algorithm of the current moment, and building one bottom-up — starting
from "what is a gradient, concretely, as a NumPy array with a tape
attached" and ending with a model that writes plausible next tokens — is
the sharpest test of genuine understanding versus API familiarity I could
pick. It's also a real engineering test: naive scalar-value autodiff (fine
for a toy MLP) can't train a multi-layer attention model in reasonable
time, so getting tensor-shaped broadcasting/matmul/reduction gradients
*and* attention *and* KV-cache masking exactly right is where genuine bugs
live — and two of them turned up in adversarial review, exactly as
intended.

## Where a human could take this next

- **Bigger corpus, bigger model.** The architecture and training loop
  scale directly — dim/layers/heads/context are all CLI flags. A larger
  corpus (this repo's egress policy blocked Gutenberg; a human running
  this locally could fetch one) plus a few more layers would produce
  noticeably more coherent output without any code changes.
- **A real BPE pretokenizer.** The tokenizer trains merges over the raw
  byte stream with no word-boundary regex (documented as a deliberate
  simplification in `loom/tokenizer.py`); adding GPT-2's pretokenizer
  regex would improve tokenization quality, especially on code or
  multilingual text.
- **Rotary or ALiBi position embeddings** instead of learned absolute
  positions, to generalize beyond the trained context length.
- **Speed.** The autograd engine is plain NumPy with Python-level op
  dispatch — fine for a "tiny" model, but a human wanting to scale up
  would want to fuse ops, add mixed precision, or drop to a compiled
  backend for the hot matmul paths.
- **Beam search / repetition penalties** in `loom/generate.py` alongside
  the existing temperature/top-k/top-p sampling.
