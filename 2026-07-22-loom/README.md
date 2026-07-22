# Loom

*A tiny transformer language model, built from scratch — no PyTorch, no TensorFlow.*

**Status: shipped.** All 4 required features work end-to-end, both stretch
features are shipped, a hostile review pass found and fixed two real bugs
(see [REVIEW.md](./REVIEW.md)), and `./demo.sh` verifies all of it —
autograd, tokenizer, model/generation, a from-scratch training run, KV-cache
correctness and speedup, and the full playground server API — in one
command. See [PLAN.md](./PLAN.md) for the architecture and feature list.

## Verify it yourself

```
pip install -r requirements.txt
./demo.sh
```

Runs the full test suite (autograd gradient checks, tokenizer round-trips,
model/KV-cache correctness), trains a fresh tiny model from nothing,
benchmarks the KV-cache, and boots the playground server to exercise every
API route — 8 steps, all green, in well under a minute.

## Quick start

```
pip install -r requirements.txt   # numpy only
python3 train.py                  # trains tokenizer + model, saves checkpoints/loom.{npz,json}
python3 sample.py --prompt "The weaver" --tokens 150
python3 server.py                 # interactive playground at http://127.0.0.1:8420
```

## What's built so far

- `loom/autograd.py` — a `Tensor` class over NumPy arrays with a full
  reverse-mode backward tape (matmul, broadcasting add/mul/div, reshape,
  transpose, softmax, layer norm, GELU, embedding gather, cross-entropy).
  Every op is gradient-checked in `tests/test_autograd.py`.
- `loom/tokenizer.py` — byte-level BPE trained from scratch on the corpus,
  lossless round-trip on any input (verified on unseen text, emoji, empty
  string).
- `loom/nn.py` — the transformer itself (causal multi-head attention,
  weight-tied output head, pre-LN residual blocks), composed only from the
  autograd primitives above.
- `train.py` — trains the tokenizer and model on `corpus/corpus.txt` (an
  original short-story collection written for this project — see below),
  Adam from scratch, warmup+cosine LR schedule. A run produced loss
  6.09 → 3.15 over 2000 steps (~6.7 min on CPU); see `checkpoints/train_log.json`.
- `sample.py` / `loom/generate.py` — temperature/top-k/top-p sampling, with
  an optional KV-cache (verified bit-identical to full recompute under
  greedy decoding — see `tests/test_model.py`).
- `server.py` + `static/playground.html` — a server-backed interactive
  playground (stretch feature): prompt the real trained model over HTTP,
  see the generated continuation, a live per-layer/per-head attention
  heatmap for it, the training loss curve, and a before/after-training
  sample comparison. Browser-tested end-to-end with Playwright (screenshots
  in dev notes) — no client-side model logic, every request is a real
  round trip to the Python engine, same pattern as this repo's Gambit
  (chess) and Formulate (spreadsheet) builds.
- `benchmark.py` — KV-cache vs. full-recompute generation benchmark
  (stretch feature): **~2.7x speedup** from incremental decoding on this
  model/context size (see below).

## KV-cache benchmark

```
$ python3 benchmark.py --tokens 45 --repeats 3
method                  mean sec     sec/token
KV-cache                  0.0678       0.00151
full recompute            0.1826       0.00406

speedup: 2.69x
```

## Corpus

`corpus/corpus.txt` is an original short-story collection ("The Loom of
Small Things", nine linked fables) written specifically for this project —
not fetched from an external source (outbound access to public-domain text
archives like Project Gutenberg is blocked by this environment's egress
policy). Being self-authored sidesteps any licensing ambiguity.

## Next

Phase 5 (verification: full test suite + demo script), Phase 6 (ship).
