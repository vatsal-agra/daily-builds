# Adversarial review

Hostile pass over the codebase looking for bugs, edge cases, silent data
corruption, and lazy shortcuts. Each finding below was fixed, and the
fix is covered by a test (existing or newly added) so it can't regress
silently.

## Findings and fixes

### 1. Corpus generator: title names the wrong animal (real data bug)
`make_corpus()` sampled the title's animal/trait *independently* from the
body's protagonist — every title had roughly a `1 - 1/20` chance of naming
an animal that never appears in its own story (e.g. "The Patient Sparrow"
about a beetle). This wasn't cosmetic: the first full training run on the
buggy corpus produced a generated fable that itself drifted from "beetle"
to "sparrow" mid-story, i.e. the model faithfully learned the corpus's own
incoherence.
**Fix:** `make_fable()` now returns the `(animal, trait)` it used, and
`make_corpus()` builds the title from that same tuple instead of drawing a
fresh one. Verified 0/600 title/body mismatches after regenerating (was
effectively unchecked before — there was no test for this because it's a
data-generation script, not library code under test). The model was
retrained from scratch on the corrected corpus before shipping.

### 2. KV-cache priming used the wrong "no cache" sentinel
`GPT.init_kv_caches()` originally returned `[None, None, ...]` (one `None`
per block). `Block.forward()` dispatches on `kv_cache is not None` to
decide whether it's in incremental-generation mode (return `(x, new_cache)`)
or ordinary training mode (return `x`). A bare `None` meaning "cache mode,
nothing cached yet" collapsed into the same branch as "not using the cache
at all," so priming the very first token crashed with
`ValueError: not enough values to unpack`.
**Fix:** `init_kv_caches()` now returns `[(None, None), ...]` — a real
tuple (so `is not None` is true → cache-mode branch) whose contents mean
"nothing cached yet." Caught immediately by `tests/test_generate.py`'s
cache/naive parity test, which now passes and stays in the suite as a
regression guard.

### 3. Non-finite gradients silently skipped clipping
`clip_grad_global_norm` clipped when `total_norm > max_norm`. In Python,
every comparison with `nan` is `False` — so a diverged run producing NaN
gradients would silently skip clipping and feed NaN straight into AdamW,
corrupting every parameter with no error, no warning, just a model that
quietly turns to NaN.
**Fix:** the function now checks `math.isfinite(total_norm)` first and
raises `FloatingPointError` naming the offending tensors instead of
continuing. Covered by `tests/test_model.py::test_nan_grad_raises_instead_of_corrupting`.

### 4. Visualizer logged a CORS error on its primary, documented use case
`viz/visualizer.html` is designed to be opened directly (`file://`, "no
server needed" — see PLAN.md). Its convenience auto-load tried
`fetch('trace.json')` unconditionally; on `file://` this is *always*
blocked by CORS, and the browser logs a console error before our `.catch`
ever runs, even though the fallback behaved correctly. A user opening dev
tools on the documented happy path would see a red error for a feature
working exactly as intended.
**Fix:** skip the fetch attempt entirely when `location.protocol ===
'file:'` and go straight to the file-picker prompt. Verified with a
headless-Chromium (Playwright) pass that asserts zero console errors while
loading a trace, switching every layer/head tab, stepping and
playing/pausing generation, and hovering a heatmap cell for the tooltip.

### 5. Missing checkpoint gave a raw, unhelpful traceback
`loom generate --ckpt-dir <typo>` raised a bare `FileNotFoundError` on
`config.json` deep in `train.py`, with no hint about what to do.
**Fix:** `load_checkpoint()` now checks for the checkpoint directory up
front and raises with an actionable message (the exact `loom train`
command to run).

### 6. Dead code
`GPT.named_modules()` was written, never called anywhere, and duplicated
what `params()` already does more usefully. Deleted rather than kept
"in case it's useful."

## Checked and found NOT to be bugs (would have been shortcuts to skip)

- **Sliding-window position reset in naive generation.** When the
  generated sequence exceeds `n_ctx`, `generate_naive` crops to the last
  `n_ctx` tokens and the model treats the crop's first token as position 0
  again. This looks like an off-by-something bug at first glance, but it's
  exactly consistent with training (the model only ever saw random
  length-`n_ctx` crops of the corpus, always at positions `0..n_ctx-1`
  relative to the crop start) — re-zeroing on each slide is what the model
  actually learned, not an approximation of it.
- **KV-cache is capped at `n_ctx` total tokens** rather than also
  supporting a sliding window — attempting to exceed it raises `ValueError`
  rather than silently producing wrong output (`tests/test_generate.py::test_cache_budget_enforced`).
  Documented directly in `generate.py`'s module docstring rather than
  quietly working around it, since a sliding KV-cache needs to evict and
  re-index positions and would meaningfully complicate the cache for a
  demo-scale model.
- **`sample_from_logits` with `top_p` zeroing an entire row.** If nucleus
  filtering were to zero every probability (it can't, in practice —
  `cutoff` is computed via `searchsorted` and is always ≥ 1 — but the code
  still defends the theoretical edge with an explicit fallback to the
  single highest-probability token) rather than dividing by zero.
- **Long, whitespace-free "words" during BPE encoding** (e.g. a 3000-byte
  run of the same character) are algorithmically the tokenizer's worst
  case (repeated full rescans of the pretoken while merges keep applying),
  but every pretoken in real prose is whitespace-bounded and short; a
  targeted test with a 3000-byte pathological pretoken still encoded in
  under a millisecond given the corpus's actual learned merges, so this
  was not worth engineering around for a natural-language tokenizer.

## Not fixed — accepted and documented as a known limitation

- **The model sometimes drifts its own protagonist mid-generation**
  (e.g. starts a fable about a "beetle" and later calls it a "sparrow"),
  independent of the corpus bug in #1. A 3-layer/96-dim model trained for
  2500 steps has no explicit mechanism forcing long-range noun consistency
  beyond what self-attention picks up incidentally, and the training
  corpus's heavy word-level overlap between animals ("the {animal}...")
  makes near-miss substitutions cheap in cross-entropy terms. This is
  called out here rather than cherry-picking only the clean generations for
  the README.
