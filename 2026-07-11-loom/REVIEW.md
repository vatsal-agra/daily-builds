# Phase 3 — Adversarial Review

Hostile pass over the Phase 2 codebase: hunting for bugs, broken edge cases,
crashes, and lazy shortcuts rather than admiring the gradcheck-passing happy
path.

## Findings

1. **[BUG, real crash] `TextDataset` can carve out a validation split
   smaller than `block_size`, crashing training mid-run.**
   `data.py`'s old split logic was `n_val = max(1, int(len(ids) *
   val_fraction))`, which only guarantees at least 1 validation token, not
   enough to form a single training example once `block_size` is larger
   than a few dozen tokens. Reproduced directly: a 360-character corpus
   (16 val tokens) with the default `block_size=64` raises
   `ValueError: val split has 16 tokens, need > block_size=64` on the very
   first `eval_every` checkpoint, after the tokenizer has already been
   trained and several training steps have already run — a real,
   demonstrable crash on a plausible input (`train.py`'s own upfront check
   only validates the *train* split is large enough, not val).
   **Fix:** `TextDataset` now takes `block_size` at construction, guarantees
   the val split is at least `block_size + 2` tokens by taking
   `max(block_size + 2, val_fraction * len)`, and for corpora too small to
   support a genuinely held-out val split, falls back to reusing the full
   corpus for both splits (flagged via `has_held_out_val = False`) instead
   of crashing. `train.py`'s eval call no longer needs its awkward
   `min(batch_size, ...)` clamp, since the split is now always large enough
   for any batch size (sampling is with replacement).

2. **[BUG, dead code] `ByteBPETokenizer._merge_rank` is written but never
   read.** It was scaffolding for a rank-based encode algorithm that was
   never implemented (encode applies merges in learned order across the
   whole sequence instead, which is simpler, self-consistent with `train()`,
   and already correctly round-trips). Carrying an unused dict around is
   exactly the kind of lazy leftover this phase exists to catch.
   **Fix:** removed `_merge_rank` entirely.

3. **[ROBUSTNESS] CLI leaked raw Python tracebacks on ordinary bad input** —
   a missing corpus file, a missing/corrupt checkpoint directory, a
   too-small corpus for the requested `--block-size`, etc. all surfaced as
   an unhandled stack trace instead of a clean message.
   **Fix:** `cli.main()` now wraps dispatch in a `try/except`, printing
   `loom: error: <message>` to stderr and exiting 1 for the exception types
   this codebase actually raises on bad input (`FileNotFoundError`,
   `ValueError`, `OSError`), while letting genuine programming-error
   exceptions (`KeyError`, `IndexError`, etc.) still surface with a full
   traceback since silently swallowing those would hide real bugs.

4. **[ROBUSTNESS] User-facing validation used `assert`, which
   `python -O` strips.** `nn.py` used `assert n_embd % n_head == 0` and
   `assert T <= self.block_size` for conditions a caller can easily violate
   (e.g. feeding a too-long sequence into `forward`). Under `-O` these
   silently vanish and the code proceeds to produce wrong-shaped output or
   an obscure numpy error instead of a clear message.
   **Fix:** converted both to explicit `raise ValueError(...)`.

5. **[ROBUSTNESS] `GPT.forward` didn't validate token ids against
   `vocab_size`.** A checkpoint/tokenizer mismatch, or any caller passing
   raw ids instead of tokenizer output, hits a raw numpy `IndexError` deep
   inside the embedding gather with no indication of what went wrong.
   **Fix:** `forward` now checks `idx` is in `[0, vocab_size)` up front and
   raises a clear `ValueError` naming the offending value.

6. **[ROBUSTNESS] Nucleus (top-p) + top-k sampling could hit `rng.choice`'s
   "probabilities do not sum to 1" error** on floating-point edge cases —
   masking out low-probability tokens and renormalizing once is
   theoretically exact but not always exactly `1.0` in float64 after
   several chained operations.
   **Fix:** added a final defensive `probs /= probs.sum()` immediately
   before `rng.choice` in `sample.py`.

7. **[MAINTAINABILITY] `GPT._block_with_attn` duplicated the entire body of
   `Block.__call__` / `CausalSelfAttention.__call__`** just to additionally
   return attention weights for the visualizer. Two independent
   implementations of the same math is exactly how a future edit silently
   desyncs training-path behavior from visualization-path behavior.
   **Fix:** `CausalSelfAttention.__call__` now takes a `return_attn=False`
   flag and returns `(out, attn_weights_or_None)`; `Block.__call__` forwards
   the flag. `GPT.forward`'s `capture_attn` path now calls the *same* code
   path as normal training/inference instead of a hand-copied parallel
   implementation — verified against the pre-fix version's output on a
   fixed seed to confirm the refactor didn't change model behavior, and
   re-verified with a fresh end-to-end gradient check on the refactored
   `Block`/`CausalSelfAttention`.

## Not changed (considered and judged acceptable)

- BPE `train()` recomputes pair frequencies from scratch every merge step
  (`O(merges * corpus_len)` rather than an incremental-count priority
  queue). At this project's scale (a few hundred merges over a few tens of
  thousands of characters) this is under two seconds; a production BPE
  trainer would do better, but optimizing it wouldn't change any observable
  behavior and isn't worth the added complexity for a from-scratch demo.
- `TextDataset` samples training positions uniformly at random with
  replacement rather than iterating true epochs. This is standard practice
  for small-corpus language-model demos of this kind and is not a bug.
- Autoregressive generation recomputes attention over the full trailing
  context at every generated token (no KV cache). This is a real, known
  performance limitation of the from-scratch implementation, not a
  correctness bug, and is out of scope for what this build promised.

## Gate

After the fixes above: re-ran the full gradient-check suite (tensor ops,
full-model end-to-end, refactored attention/block), re-ran the training
smoke test, and re-ran the crash repro from finding #1 — it now completes
cleanly. See `tests/` (Phase 5) for the regression tests that lock these in.
