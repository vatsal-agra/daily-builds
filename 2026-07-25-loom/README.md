# Loom 🧵

A GPT-style decoder-only Transformer language model, built entirely from
scratch in Python + NumPy: byte-level BPE tokenizer, multi-head causal
self-attention, LayerNorm, GELU MLPs — every `backward()` derived and
verified by hand, no `torch`/`jax`/`transformers`/autograd anywhere.
Trained end-to-end on an original corpus of procedurally generated fables,
it writes new ones.

Attention *is* a loom: each token's new representation is a weighted weave
of every earlier token's **value** vector, with weights computed from
**query·key**. The visualizer makes that literal.

## What it is

- **`loom/tokenizer.py`** — byte-level BPE trained from scratch (merge
  learning, encode, decode), exact round trip, deterministic.
- **`loom/layers.py` / `model.py`** — GPT architecture (embedding → N
  transformer blocks → final LayerNorm → weight-tied output head) with
  hand-derived forward **and** backward passes for every layer. Verified
  against numerical (finite-difference) gradients, including the
  tied-weight embedding/output-head gradient, which sums contributions
  from two places.
- **`loom/optimizer.py`** — AdamW, global-norm gradient clipping (with a
  NaN/Inf guard — see `REVIEW.md` #3), warmup + cosine LR decay.
- **`loom/train.py`** — the real training loop: tokenizes the corpus,
  minibatches, trains, checkpoints.
- **`loom/generate.py`** — autoregressive sampling with
  temperature/top-k/top-p, plus a KV-cached fast path that is provably
  identical output to the naive path (not just visually similar — checked
  token-for-token).
- **`viz/visualizer.html`** — self-contained (open the file directly, no
  server) attention heatmap + step-through generation viewer.
- **`corpus/make_corpus.py`** — generates the original training corpus.

## Why a made-up corpus, not a real book

The sandbox this was built in can't reach arbitrary external hosts
(Project Gutenberg etc. are blocked), and reproducing a real public-domain
text from memory risks silent transcription errors. So the training data
is "The Loom Fables" — an original, procedurally generated corpus (600
short animal fables from a template + word-bank generator, ~387KB).
License-clean, and honestly, better suited to the goal: its low entropy
and repetitive structure are exactly what let a tiny, CPU-only, ~15-minute
training run produce genuinely coherent output instead of gibberish.
This tradeoff — and where it shows up in the model's behavior — is
documented in `REVIEW.md`, not hidden.

## Quick start

```bash
pip install numpy   # the only dependency
bash demo.sh         # runs every test, loads the shipped checkpoint,
                      # generates real samples, benchmarks KV-cache vs
                      # naive generation, exports a visualizer trace
```

Then open `viz/visualizer.html` in a browser and load `viz/trace.json`
via the file picker (or serve the folder over http and it auto-loads).

To train your own from scratch (~15 minutes on CPU, reproduces the shipped
checkpoint exactly since all seeds are fixed):

```bash
python3 -m loom.cli train                      # writes checkpoints/loom-small/
python3 -m loom.cli generate --prompt "" --max-new-tokens 200 --temperature 0.8
python3 -m loom.cli generate --prompt "" --use-cache --max-new-tokens 55
python3 -m loom.cli bench --max-new-tokens 60  # KV-cache vs naive, speed + parity
python3 -m loom.cli viz --text "The clever fox wanted"
```

## Feature list (all shipped)

**Required:**
1. From-scratch byte-level BPE tokenizer — train/encode/decode, exact
   round trip on 5 test samples including empty string and multi-byte UTF-8.
2. From-scratch Transformer forward + backward — every layer's gradient
   verified against finite differences (max relative error ~1e-5 across
   84 sampled parameters of the full tied-weight model).
3. Real training loop — AdamW + warmup/cosine LR + grad clipping; loss
   fell from **5.97 → ~0.18** over 2500 steps on the real corpus, train
   and val loss tracking closely (no runaway overfitting).
4. Autoregressive generation with temperature/top-k/top-p sampling.

**Stretch:**
5. KV-cache generation — **6.1× faster** than the naive path for a
   40-token continuation in the benchmark run, with byte-for-byte
   identical output to the uncached path at the same seed (this is
   checked automatically in `tests/test_generate.py`, not just claimed).
6. Interactive HTML attention + generation visualizer — per-layer/head
   attention heatmaps (the causal mask is visible as the empty upper
   triangle) and a step-through view of next-token probabilities during
   generation, with play/pause. Verified with a headless-Chromium pass:
   zero console errors while loading a trace, switching every tab,
   stepping, playing, and hovering the heatmap for tooltips.

## Sample output (from the shipped checkpoint, `demo.sh`)

```
The Proud Bear

Long before the river changed its course, there lived a proud bear near
the deep wood. The bear had wanted a way home before dark for as long as
anyone could remember, and today seemed, at last, like the day to get it.
Just as the bear was cert[ain of success...]
```

## Known limitations (see `REVIEW.md` for the full adversarial review)

- The model occasionally drifts its own protagonist mid-fable (measured:
  1/5 sampled generations at different seeds). No explicit long-range
  entity-consistency mechanism beyond what attention picks up incidentally.
- Prompts that don't look like a fable opening (e.g. `"The clever fox"`,
  a sentence fragment) produce weak, sometimes non-sequitur continuations
  — the model is a strong in-distribution generator, not a general-purpose
  few-shot continuer, because the training corpus is intentionally narrow.

## Why this, today

Every prior build in this repo has reimplemented a classic CS algorithm —
SAT solvers, a VCS, a spreadsheet engine, ray tracers, compression, a
regex engine — but none had touched the architecture currently reshaping
software. Deriving backprop through softmax-attention, LayerNorm, and a
GELU MLP by hand — then checking it numerically — is a real test of
whether you understand what `.backward()` normally hides.

## Where a human could take this next

- Swap the synthetic fable corpus for a real (license-clear, properly
  fetched) text corpus and scale up `n_embd`/`n_layer`/`n_ctx` — the
  architecture doesn't change, just the config.
- Add rotary position embeddings (RoPE) instead of learned absolute
  positions — would remove the `n_ctx` hard cap on the KV-cache path.
- Batch the KV-cache prefill (currently primes one token at a time in a
  Python loop — see `generate.py`'s docstring) for real speed at longer
  prompts.
- Multi-query / grouped-query attention to shrink the KV-cache further.
- A tiny web UI (the visualizer is read-only) that lets you type a prompt
  and watch tokens stream in live, backed by `loom/cli.py generate`.
