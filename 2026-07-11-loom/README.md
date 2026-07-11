# Loom

*Status: Shipped. All 4 required + 3 stretch features complete, adversarially
reviewed, and verified: 84/84 automated tests green (unit tests, finite-
difference gradient checks, a full end-to-end GPT gradient check, a headless-
Chromium UI smoke test) plus an 8-check `demo.sh` walking the real CLI
end-to-end. See "Verification" below for how to reproduce.*

A Transformer language model trained on a from-scratch tensor autodiff
engine — no PyTorch, no JAX, no `autograd`. `numpy` is used only as a fast
array container and matmul; every gradient is hand-derived and verified by
finite-difference checking.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

## What's working so far

- `loom/tensor.py` — the autodiff engine (matmul, broadcasting arithmetic,
  reductions, softmax, layernorm, GELU, embedding gather, causal masking,
  cross-entropy). Every op gradient-checks to ~1e-9 relative error against
  finite differences (`loom/gradcheck.py`).
- `loom/nn.py` — a GPT-style decoder-only Transformer (multi-head causal
  self-attention, LayerNorm, GELU MLP, tied output head) built purely from
  `tensor.py` ops. The full model's backward pass gradient-checks correctly
  across all parameter tensors with no model-specific backward code.
- `loom/tokenizer.py` — byte-level BPE trained from scratch, exact round-trip
  on arbitrary text (verified on unicode and the full 256-byte range).
- `loom/optim.py` + `loom/train.py` — a from-scratch Adam optimizer and a
  training loop that demonstrably drives loss down on real text
  (`python -m loom.cli train corpus/hollow_loom.txt --steps 300` takes loss
  from ~6.3 to ~0.6 on the bundled corpus).
- `loom/sample.py` + `loom/checkpoint.py` — temperature/top-k/top-p
  generation from a saved checkpoint.
- `loom/viz.py` — a self-contained interactive HTML page: the real loss
  curve, a scrubbable/playable token-by-token generation replay, and
  per-layer/per-head attention heatmaps, all populated from an actual
  forward pass. Verified with headless Chromium: zero console errors,
  tabs/scrubbing/hover tooltips all exercised and screenshotted.
- `loom/demo.py` — `python -m loom.cli demo` trains a tokenizer + model on
  the bundled corpus in ~17s on CPU, prints an untrained-vs-trained
  comparison (both the generated text and an objective cross-entropy
  number), and writes `loom_demo_viz.html`.
- `loom/cli.py` — `python -m loom.cli {train, generate, tokenize, gradcheck,
  viz, demo}`.

## Verification

```
python3 -m unittest discover -s tests -q   # 84 tests: ~7s
bash demo.sh                                # full CLI walkthrough: ~35s
```

`tests/` covers: every `tensor.py` op against finite-difference gradients,
a full end-to-end GPT gradient check across all 28 parameter tensors, a
functional causal-masking correctness check (not just gradients), BPE
round-trips (unicode, full byte range, empty input), Adam convergence on a
convex quadratic, the `TextDataset` val-split crash regression from
`REVIEW.md`, sampling edge cases (including the empty-prompt/zero-tokens
regression), a checkpoint save/load round trip that reproduces identical
generations, a full tokenizer→train→generate→viz pipeline smoke test, and a
headless-Chromium test that loads the real visualizer and checks for
JavaScript console errors while exercising its controls.

Full feature list, architecture rationale, and phase-by-phase history in
[`PLAN.md`](./PLAN.md) and [`REVIEW.md`](./REVIEW.md).
