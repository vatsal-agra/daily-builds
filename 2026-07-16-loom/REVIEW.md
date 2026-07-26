# Adversarial review (Phase 3)

Hostile pass over the Phase 2 core build (tensor engine, tokenizer, model,
training loop, generation). Method: read every code path looking for
unhandled edge cases, ran targeted scripts to try to trigger crashes/wrong
answers (causal-leakage probe, steps=0, exact-boundary corpus length,
missing-file paths, `--seed` reproducibility claim), and re-read the public
API surface for anything unused/unexercised.

## Findings

1. **CRITICAL-ish (misleading reproducibility): `--seed` did not control
   weight initialization.** `loom/model.py` drew all parameter tensors from
   a single module-level `np.random.default_rng(1234)` created at import
   time. `loom.py train --seed N` only threaded `N` into the *batch
   sampling* RNG inside the training loop — two runs with different
   `--seed` values produced byte-identical initial weights every time,
   silently defeating the documented reproducibility contract of the flag.
   **Fix:** `GPT` now takes an explicit `seed` and builds its own
   `np.random.default_rng(seed)`, threaded down through every `Linear`/
   `LayerNorm`/embedding parameter draw. `loom.py train --seed N` now seeds
   both weight init and batch sampling from the same `N`.

2. **Off-by-one corpus-length validation crashes with a raw NumPy error.**
   Both `cmd_train`'s pre-flight check and `get_batch`'s guard rejected
   corpora with `len(ids) <= block_size`, but `get_batch` actually needs
   `len(ids) - block_size - 1 >= 1` (one extra token so there's a valid
   target `y` past the final `x` window). A corpus of exactly
   `block_size + 1` tokens passed both guards and then crashed inside
   `rng.integers(0, 0, ...)` with NumPy's own `ValueError: high <= 0` —
   not a message a user could act on. **Fix:** both checks now require
   `len(ids) >= block_size + 2`, with a clear message naming the shortfall.

3. **`--steps 0` (or any run that leaves `history` empty) crashed with an
   unhandled `IndexError`** in the final `"Loss: {history[0][1]} -> ..."`
   summary print. **Fix:** `cmd_train` now validates `--steps >= 1` up
   front with a clean error before doing any work.

4. **Raw Python tracebacks on the single most common user mistakes** —
   pointing `--corpus`/`--tokenizer`/`--checkpoint` at a path that doesn't
   exist (`FileNotFoundError`), or a corrupted/hand-edited tokenizer JSON
   (`json.JSONDecodeError`/`KeyError`). None of these were caught anywhere
   in `loom.py`. **Fix:** every file-loading call site in `loom.py` is now
   wrapped and reports a clean `ERROR: ...` message + exit code 1 instead
   of a stack trace.

5. **Dead engine surface: `Tensor.cat()` and `Tensor.__getitem__` were
   implemented, gradient-checked, and never used anywhere in the actual
   model.** Multi-head attention splits/merges heads with `reshape` +
   `permute` alone, so these two ops existed purely to pad out the engine.
   **Fix:** removed both (and their now-pointless gradcheck entries) — the
   engine's public surface now exactly matches what `loom/model.py`
   exercises, which is also exactly what is gradient-checked.

6. **Latent trap: `Tensor.shape` was a plain attribute set once at
   `__init__`, not derived from `.data`.** Currently harmless (every
   existing code path that reassigns `.data` — Adam's step, checkpoint
   loading — keeps the same shape), but a future direct `t.data = <new
   array>` with a different shape would silently desync `.shape` from
   reality with no error. **Fix:** `shape` is now a `@property` computed
   from `self.data.shape`, so it can never go stale. This also let us
   delete the manual `p.shape = p.data.shape` line `load_checkpoint` had
   to carry as a workaround.

## Verified during the fix pass

- Causal masking has **zero leakage**: changing only the last token of an
  input and re-running the forward pass leaves every earlier position's
  logits bit-for-bit identical (checked with an explicit before/after
  diff, not just "it looks right").
- All 18 gradient checks (16 ops + the full transformer block) still pass
  after the `cat`/`__getitem__` removal and the `Tensor.shape` property
  change.
- Re-ran `train-tokenizer` -> `train` -> `generate` end-to-end after every
  fix above; no regressions.

Gate: a fresh run-through (see `demo.sh` in Phase 5) hits zero of the six
issues above.
