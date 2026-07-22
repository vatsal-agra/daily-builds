# Loom

*A tiny transformer language model, built from scratch — no PyTorch, no TensorFlow.*

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end: a from-scratch BPE tokenizer, a NumPy tensor autograd engine
(every backward rule gradient-checked against finite differences), a
transformer trained on a real corpus with visibly decreasing loss, and
autoregressive generation with temperature/top-k/top-p sampling. See
[PLAN.md](./PLAN.md) for the full architecture and feature list.

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
  playground (stretch feature, in progress).

## Corpus

`corpus/corpus.txt` is an original short-story collection ("The Loom of
Small Things", nine linked fables) written specifically for this project —
not fetched from an external source (outbound access to public-domain text
archives like Project Gutenberg is blocked by this environment's egress
policy). Being self-authored sidesteps any licensing ambiguity.

## Next

Phase 3 (adversarial review), Phase 4 (KV-cache benchmark + playground
polish), Phase 5 (verification), Phase 6 (ship).
