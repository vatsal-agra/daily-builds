# Loom

A tiny GPT-style language model built from scratch in Python: a hand-rolled
tensor autodiff engine, a byte-pair-encoding tokenizer, a decoder-only
Transformer, an Adam-trained optimizer loop, and autoregressive sampling —
no PyTorch, no JAX, no autograd library. See [PLAN.md](PLAN.md) for the
full architecture and feature list.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end:

- `python3 loom.py train-tokenizer` trains a byte-level BPE tokenizer from
  scratch on `data/corpus.txt` and round-trips it exactly.
- `loom/tensor.py` is a from-scratch reverse-mode autodiff engine over
  NumPy arrays; `loom/model.py` builds a real multi-head causal-attention
  Transformer out of it. Every op is gradient-checked against numerical
  finite differences (`python3 loom.py gradcheck` — 18/18 passing,
  including a full transformer block).
- `python3 loom.py train` trains the model with Adam + LR warmup/cosine
  decay + gradient clipping; loss measurably decreases (e.g. 6.49 -> 2.51
  over 150 steps on the bundled corpus) and checkpoints save/reload.
- `python3 loom.py generate` / `chat` sample from a trained checkpoint with
  greedy, temperature, top-k, or top-p (nucleus) decoding.

**Status: Phase 3 (adversarial review) complete.** See [REVIEW.md](REVIEW.md)
for the full hostile-review pass — 6 real issues found and fixed, including
a reproducibility bug (`--seed` silently didn't control weight
initialization), an off-by-one in corpus-length validation that crashed
with a raw NumPy error instead of a clean message, an unhandled crash on
`--steps 0`, raw tracebacks on missing/corrupt files, dead unused autodiff
ops, and a latent `Tensor.shape` staleness trap. All 17 gradient checks
still pass after the fixes.

**Status: Phase 4 (stretch + polish) complete.** Shipped stretch feature:
`python3 loom.py attn-viz` runs a real forward pass on a prompt and renders
an interactive, theme-aware, self-contained HTML heatmap of the actual
per-layer/per-head attention weights (layer/head picker, hover tooltip with
exact weight + token pair, causally-masked cells visually distinguished
from near-zero-but-valid attention) — verified with a headless-Chromium
smoke test (renders, zero JS console errors, tooltip and layer/head
switching all confirmed working, both light and dark). Polish pass added:
clean errors on empty/whitespace prompts, a truncation notice when a
prompt exceeds the model's context window, and Ctrl-C handling in the chat
REPL.

**Status: Phase 5 (verification) complete.** `tests/test_loom.py` (32 unit
tests covering tensor ops, tokenizer round-trips incl. unicode/emoji/empty
string, model shape/causality/seed-determinism, training loss-decrease,
checkpoint round-trips, and generation determinism/vocab-safety) and
`demo.sh` (17 end-to-end checks driving the real CLI, including edge cases:
missing files, `--steps 0`, whitespace-only prompts) both run green —
`bash demo.sh` in full.

Final shipping polish (Phase 6) still to come.

## Quick start

```
pip install -r requirements.txt
python3 loom.py train-tokenizer --vocab-size 400 --out tokenizer.json
python3 loom.py train --tokenizer tokenizer.json --out checkpoint.npz --steps 600
python3 loom.py generate --checkpoint checkpoint.npz --tokenizer tokenizer.json \
    --prompt "Old Maren" --max-new-tokens 150
python3 loom.py attn-viz --checkpoint checkpoint.npz --tokenizer tokenizer.json \
    --prompt "Old Maren said" --out attention.html
```
