# Loom

A GPT-style transformer language model, built entirely from scratch in
NumPy — tokenizer, architecture, backpropagation, training, and sampling,
all hand-written, with no PyTorch/TensorFlow/JAX and no autodiff library.

> **Status: Phase 3 complete (adversarial review).** The 4 required features
> work end-to-end and have survived a hostile review pass — see REVIEW.md
> for the 6 real issues found (a visualizer crash, an XSS-adjacent
> unescaped-`</script>` gap, raw tracebacks leaking on ordinary bad input,
> a missing-directory crash, a code-quality shortcut, and a test-coverage
> gap) and their fixes. Phase 4 (stretch features + polish) and Phase 5
> (verification) are still to come — see PLAN.md.

## What's here so far

- `loom/tokenizer.py` — byte-level BPE tokenizer, trained from scratch.
- `loom/nn.py` / `loom/model.py` — the transformer itself: embeddings,
  causal multi-head self-attention, pre-norm residual blocks, GELU
  feed-forward, weight-tied output head. Every op has a hand-written
  `backward()`.
- `loom/gradcheck.py` — finite-difference gradient checking that proves the
  hand-written backprop is analytically correct.
- `loom/optim.py` / `loom/train.py` — Adam + warmup/cosine LR schedule +
  grad clipping, and the minibatched training loop with checkpointing.
- `loom/sample.py` — temperature / top-k / top-p autoregressive generation.
- `cli.py` — `tokenizer-train`, `gradcheck`, `train`, `sample`, `demo`.
- `tests/` — 51 unit tests (all green) covering tokenizer round-trips,
  gradient checks across depths/batch sizes/edge cases (seq_len=1, batch=1),
  causal-mask leakage, checkpoint round-tripping, loss-decreases-with-
  training regression tests, and (new in Phase 3) the visualizer's crash
  and script-injection regressions.

## Try it

```bash
pip install -r requirements.txt
python3 cli.py gradcheck                 # prove backprop is correct
python3 cli.py train --steps 2000        # train on the bundled corpus
python3 cli.py sample --prompt "ROMEO:"  # generate text
```

See PLAN.md for the full architecture writeup and feature list.
