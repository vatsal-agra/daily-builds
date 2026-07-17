# Sprout

A tiny GPT-style language model, trained entirely from scratch — byte-level
BPE tokenizer, transformer forward *and* backward pass, Adam optimizer, and
sampler, all hand-written in NumPy. No PyTorch, no TensorFlow, no JAX, no
autograd library of any kind. Every gradient is derived by hand and checked
against finite differences before being trusted (`gradcheck.py` — all 28+
checks pass, most under 1e-7 relative error).

See [`PLAN.md`](./PLAN.md) for the architecture, [`REVIEW.md`](./REVIEW.md)
for the adversarial-review findings and fixes, and
[`MODEL_CARD.md`](./MODEL_CARD.md) for the real, auto-generated results of
the checkpoint shipped in this repo.

## Why this one

Every other build in this repo's history is a classical algorithm —
solvers, renderers, compilers, databases. This is the one thing missing:
a generative model, built with the same "no shortcuts, derive it yourself"
ethic. The interesting engineering isn't the training loop (that part's
easy); it's getting the backward pass through multi-head attention, layer
norm, and GELU exactly right, and being able to *prove* it's right before
spending a single second on an actual training run.

## What's here (all 4 required features, working end-to-end)

- **`sprout/tokenizer.py`** — byte-level BPE tokenizer. Trains merges from
  raw corpus bytes, so any input string encodes without ever needing an
  `<unk>` token (round-trips even unicode never seen during training).
- **`sprout/nn.py`** — the transformer itself: `Linear`, `LayerNorm`,
  `Embedding`, causal multi-head self-attention (einsum-based, both
  directions), GELU `MLP`, residual `Block`s, and the full `GPT` model —
  every module implements both `forward()` and a hand-derived `backward()`.
- **`sprout/gradcheck.py`** — the correctness gate. Numerically verifies
  every parameter's analytic gradient against finite differences, for
  every module individually and for the whole model end-to-end through a
  real cross-entropy loss. **Run it yourself:** `python3 sprout/gradcheck.py`
- **`sprout/optim.py`** — Adam (Kingma & Ba, 2014) from scratch, with
  global gradient-norm clipping.
- **`sprout/train.py`** — the training loop: minibatching over the token
  stream, train/val loss tracking, checkpointing, periodic sample
  generation so progress is visible live.
- **`sprout/generate.py`** — autoregressive sampling with temperature,
  top-k, and top-p (nucleus) filtering, plus a CLI completion/chat mode.
- **`sprout/data/make_corpus.py`** — generates the training corpus: ~170KB
  of original text (fables, dialogues, field notes) from hand-written
  templates + an original cast of characters/animals/places, so there's no
  scraped data and no network dependency.
- **`sprout/tests/test_all.py`** — 22 unit tests covering the tokenizer,
  the model, the optimizer, sampling edge cases, and the training loop.

## Stretch features

- **`sprout/attention_viz.py`** — runs a prompt through a trained
  checkpoint and writes a self-contained interactive HTML page
  (`attention_viz.html`) with real per-layer, per-head attention
  heatmaps: a layer/head picker and a query-token slider that highlights
  exactly which earlier tokens that query actually attended to. Every
  number in it comes straight out of the model's own forward-pass cache —
  nothing illustrative or faked.
- **`sprout/server.py`** — a zero-dependency `http.server` playground.
  Every "Generate" click is a real network round trip to a real Python
  forward pass — the browser holds no model logic (same pattern this
  repo's Gambit and Formulate builds used). Verified under concurrent
  requests from multiple simultaneous clients — this is what surfaced and
  fixed the shared-RNG race documented in `REVIEW.md`.
- **`sprout/model_card.py`** — auto-generates `MODEL_CARD.md` straight from
  a checkpoint's real training history and live sample generations,
  including an explicit "honest assessment" section instead of marketing
  copy.

## Results (the checkpoint shipped in this repo)

A 4-layer, 4-head, 128-dim model (**932,608 parameters**) trained for
**1,600 steps** (~43 minutes on CPU) on the 170KB original corpus:

| step | train_loss | val_loss |
|---:|---:|---:|
| 1 | 6.256 | 6.170 |
| 100 | 3.872 | 3.860 |
| 400 | 0.590 | 0.627 |
| 800 | 0.268 | 0.305 |
| 1600 | **0.217** | **0.292** |

Final validation perplexity: **1.34**. Untrained-model sanity check: initial
loss (6.256) lines up almost exactly with `ln(vocab_size=512) = 6.238`, i.e.
a fresh random model starts out indistinguishable from uniform guessing —
an independent, non-gradient-based signal that the loss/softmax math is
correct.

Sample generation (temperature 0.8, top-k 40):

```
the fox and the toad agreed that speed was not the thing worth arguing about.

There was a newt who envied the newt for its wings, and a stoat who envied
the stoat for its den. Percy watched them trade c...
```

Full loss curve and more samples in [`MODEL_CARD.md`](./MODEL_CARD.md).

**Honest read:** at this size and this little data, the model has largely
learned to recombine the corpus's own sentence templates with swapped
character/animal/place names — it produces fluent, well-punctuated English
because those templates are extremely repetitive and low-entropy, not
because a ~1M-parameter model has learned general language. That's the
expected, honest outcome for a CPU-trained toy model, and exactly why
`gradcheck.py` (not sample quality) is the real correctness evidence here.

## Quickstart

```bash
cd sprout
pip install -r requirements.txt

python3 gradcheck.py                              # verify the math (should all say OK)
python3 generate.py --checkpoint checkpoints/sprout.pkl --prompt "the fox"
python3 server.py                                 # web playground at localhost:8420
python3 attention_viz.py --prompt "the fox and the otter argued about"
python3 model_card.py                             # regenerate MODEL_CARD.md

# to retrain from scratch instead of using the shipped checkpoint:
python3 data/make_corpus.py
python3 train.py --steps 1600                      # ~30-45 min on CPU

# everything above, automated, plus edge-case checks:
./demo.sh
```

## Where a human could take this next

- Scale up: more layers/heads/dims and a real corpus (even a public-domain
  book) would move this from "recombines templates" to "generalizes" —
  the architecture doesn't change, only the numbers and the data.
- KV-caching for generation (currently every sampling step reruns the full
  forward pass over the whole context — fine at this scale, wasteful at
  any larger one).
- Weight-tie the output projection to the token embedding (halves the
  largest parameter matrix, standard in real GPT implementations, skipped
  here for simpler backward-pass bookkeeping).
- Multi-query/grouped-query attention, RoPE positional encoding, or
  RMSNorm instead of LayerNorm — all straightforward swaps once the
  gradient-check harness exists, since any new module just needs the same
  forward/backward/gradcheck treatment.
- The attention visualizer only shows one prompt at a time; a batch mode
  comparing attention patterns across several prompts side by side would
  make the "what did it actually learn" story a lot more concrete.
