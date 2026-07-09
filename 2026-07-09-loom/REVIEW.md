# Adversarial Review (Phase 3)

Hostile pass over the Phase 2 core build: benchmarked the hot path,
reproduced crashes with malformed/boundary CLI inputs, and read every
module looking for dead code and silent-failure UX. Six issues found, all
fixed below. Re-verified after fixing: `gradcheck` still reports zero
regressions, and every repro command below now fails cleanly (or succeeds)
instead of crashing.

## 1. CRITICAL (performance): `Tensor.__pow__` was 50x slower than it needed to be

`gelu(x)` computes `x ** 3` on every MLP forward pass, and NumPy's `**`
operator falls back to a slow generic ufunc path for integer exponents
outside `{-1, 0, 1, 2}` on this platform:

```
pow(2):  0.018s / 50 calls   (fast path)
pow(3):  1.923s / 50 calls   (slow path — 100x slower than pow(2))
pow(4):  1.955s / 50 calls   (slow path)
```

That made the "tiny" preset (dim=64, 2 layers, 4 heads) train at roughly
**1 second per step** — a 1500-step demo run would have taken ~25 minutes,
and profiling confirmed `Tensor.__pow__` alone accounted for over 20% of
total wall-clock time in a training step.

**Fix:** added `_pow(x, power)` in `tensor.py`, computing integer powers
by exponentiation-by-squaring (plain multiplication only) instead of
`x ** power`, used by both the forward and backward passes of
`Tensor.__pow__`. Verified `gradcheck` still passes (same relative errors,
~1e-11) and re-measured training speed: **~165ms/step** at batch_size=16
on the tiny preset — roughly a 6x improvement end to end once combined
with the batch-size tuning in Phase 4.

## 2. CRITICAL (crash): `Dataset` could hand out a validation split shorter than one block

`Dataset.__init__`'s train/val split only checked that the *whole* corpus
had at least `block_size + 1` tokens, not that *each split* would. Whenever
`block_size + 1 <= len(corpus) < 2 * (block_size + 1)`, the clamp logic
silently produced a validation split shorter than `block_size + 1`,
and the first call to `get_batch(..., 'val')` crashed deep inside NumPy:

```
$ python3 -c "... Dataset(ids, block_size=299, ...).get_batch(4, 'val')"
ValueError: high <= 0
```

(reproduced with the bundled 516-character `quickstart.txt` corpus and
`--block-size 299` — not a contrived case, a real corpus/flag combination
a user would plausibly try).

**Fix:** `Dataset.__init__` now checks the actual precondition
(`len(ids) >= 2 * (block_size + 1)`) up front and raises a clear,
actionable `ValueError` naming the fix (lower `--block-size` or use a
larger corpus) instead of surfacing a cryptic NumPy internals error three
calls later.

## 3. MODERATE (UX): raw tracebacks on common user mistakes

Three easy-to-hit paths threw uncaught Python exceptions straight to the
terminal instead of a clean CLI error: `generate`/`chat`/`viz` against a
checkpoint path that doesn't exist yet, `generate --prompt` containing a
character the model was never trained on, and `viz --prompt ""`.

**Fix:** `main()` now wraps command dispatch in a `try/except` that turns
`FileNotFoundError` / `ValueError` / `AssertionError` into a one-line
`error: ...` message on stderr and a nonzero exit code, with a pointer to
`train` for the missing-checkpoint case specifically. `chat`'s REPL loop
already caught bad-vocabulary errors per turn (so one typo doesn't kill
the session); that behavior is preserved.

## 4. MINOR (dead code): unused imports in `cli.py`

`numpy`, `json`, and `save_checkpoint` were imported in `loom/cli.py` but
never referenced — leftovers from an earlier draft where checkpoint saving
was going to be called directly from the CLI layer instead of from
`train.py`. Removed.

## 5. MINOR (UX): `train --out`/`--log` to a new subdirectory failed after paying the full training cost

If `--out some/new/dir/model.npz` pointed at a directory that didn't exist
yet, training would run to completion and *then* crash on `np.savez`,
silently discarding all the compute. Fixed by creating the parent
directories of `--out` and `--log` before training starts, not after.

## 6. MINOR (UX): `viz` silently truncated long prompts

`attention_trace.trace()` truncates a prompt to the model's context length
without saying so, which could make a "why does this attention map only
cover half my prompt" investigation confusing. Fixed with a note printed
by the CLI when truncation will occur.

## Verification

- `./loom_cli gradcheck` — still all-pass after the `_pow` rewrite (23
  primitive-op checks + full-model check, max relative error unchanged at
  ~1e-11 / ~6e-6).
- Reproduced and re-tested all six issues above; all now behave as
  described in the fixes.
- Fresh run-through of `demo` (see PHASE 5 verification) hits none of the
  above.
