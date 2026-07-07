# Adversarial review

Phase 3: 8 independent review passes were run against the Phase 2 codebase
(line-by-line scan, removed/missing-invariant audit, cross-file tracer,
reuse, simplification, efficiency, altitude, and CLAUDE.md conventions),
each spawned as an isolated agent with no visibility into the others'
findings, so they wouldn't just echo each other. Every correctness finding
below was independently reproduced with a runnable repro before being
"confirmed" - nothing here is taken on an agent's word alone. Three of the
angles (line-by-line, missing-invariant, cross-file) converged on the same
`data.py` off-by-one and `generate.py` `top_k=0` bug independently, which is
a good sign the review was actually finding real things rather than
hallucinating plausible-sounding ones.

## Confirmed bugs (fixed)

1. **`loom/data.py` - off-by-one crashes on minimum-length corpus splits.**
   `rng.integers(0, len(ids) - block_size - 1, ...)` used an upper bound one
   too small. Repro: a corpus split of exactly `block_size + 1` tokens (the
   shortest split that should ever work - it has exactly one valid window)
   raised `ValueError: high <= 0` instead of returning that one window; for
   any longer split, the very last valid start index was silently excluded
   from ever being sampled. **Fix:** upper bound is now `len(ids) -
   block_size` (exclusive), matching what `y = ids[s+1 : s+block_size+1]`
   actually needs. Regression tests: `tests/test_data.py`.

2. **`loom/generate.py` - `top_k=0` (and negative `top_k`) silently did
   nothing instead of erroring.** Python's `-top_k` for `top_k=0` is `-0 ==
   0`, so `np.partition(logits_row, 0)[0]` picked the *minimum* logit as the
   threshold - the opposite of "keep the top 0" - and nothing got filtered.
   Negative `top_k` had the same silent-wrong-answer shape. Repro:
   `_logits_to_probs(logits, top_k=0, ...)` returned every token with
   nonzero probability. **Fix:** `top_k < 1` now raises `ValueError`
   immediately. Regression test:
   `test_generate_rejects_top_k_zero_or_negative`.

3. **`loom/tensor.py` - `Tensor.transpose` computed the wrong inverse
   permutation for axis lists mixing negative and positive indices.**
   `inv = np.argsort(axes)` sorted the *raw* axis values (e.g. `(0, -1, 1)`),
   not axes normalized to `0..ndim-1`, so `argsort((0, -1, 1))` diverges from
   the correct `argsort((0, 2, 1))`. Repro: `Tensor(...).transpose(0, -1,
   1)` followed by `.backward()` raised a broadcast-shape `ValueError` in
   the backward closure. Not hit by any internal call site (`nn.py` only
   ever uses all-positive axes) but a live bug in the public `Tensor` API.
   **Fix:** normalize axes with `a % self.ndim` before `argsort`. Regression
   test: `test_transpose_with_negative_axes` (also checks the gradient
   matches the equivalent all-positive-axes call exactly).

4. **`loom/tokenizer.py` - `decode()` raised a raw `KeyError` for any
   out-of-range or negative token id**, reachable directly through `loom
   tokenizer decode <ids>` on arbitrary user input (`generate`/`viz` never
   hit this in practice, since their ids always come from `encode()` or a
   `vocab_size`-wide softmax). **Fix:** `decode()` now raises a clear
   `ValueError` naming the invalid id and the valid range. Regression test:
   `test_decode_rejects_out_of_range_ids`.

5. **`loom/nn.py` - `Module.load_state_dict` did no shape or key validation**
   before overwriting `t.data`, so a checkpoint whose `config.json` and
   `weights.npz` came from different runs (mismatched `n_embd`/`n_layer`/
   etc.) would load without error and only fail later with a confusing
   shape-mismatch traceback deep inside a forward pass. **Fix:** checks for
   missing keys (raises `KeyError` naming them) and shape mismatches (raises
   `ValueError` naming the tensor and both shapes) before touching any data.
   Regression tests: `test_load_state_dict_rejects_shape_mismatch`,
   `test_load_state_dict_rejects_missing_keys`.

6. **`loom/train.py` - `load_checkpoint` never cross-checked that the
   tokenizer's actual `vocab_size` matched `config.json`'s.** A checkpoint
   directory assembled from two different runs (or a `tokenizer.json`
   retrained in place) would load silently; `generate`/`viz` would then only
   fail with a raw `IndexError` the first time a sampled id exceeded the
   model's embedding table. **Fix:** `load_checkpoint` now raises a clear
   `ValueError` naming both files and both vocab sizes when they disagree.
   Regression test: `test_load_checkpoint_rejects_vocab_size_mismatch`.

7. **`loom/tokenizer.py` - the `vocab_size >= 256` invariant was a bare
   `assert`,** which `python -O`/`PYTHONOPTIMIZE=1` strips entirely,
   silently training a smaller-than-requested (or, for negative input, a
   plain 256-token) tokenizer instead of rejecting bad input. **Fix:**
   explicit `if vocab_size < 256: raise ValueError(...)`. Regression test:
   `test_train_rejects_vocab_size_below_256`.

8. **`loom/viz.py` - a 0-layer model crashed the visualizer's JS.**
   `GPT(..., n_layer=0, ...)` is a fully valid, trainable model (`--n-layer`
   has no CLI minimum), but `_collect_attention` then produces an empty
   `attnLayers` list while the page unconditionally called `draw()`, which
   indexed `DATA.attnLayers[0]` -> `undefined` -> uncaught `TypeError` that
   aborted the rest of the `<script>` block (so the embedding-PCA scatter,
   defined later in the same block, never rendered either). **Fix:** `draw()`
   now checks `DATA.nLayer === 0` and renders an explanatory note instead.
   Verified with a real headless-browser run (zero `pageerror` events) in
   addition to the regression test `test_render_visualizer_handles_zero_layer_model`.

## Deeper fix: `no_grad()` mode (not just a bug fix)

The altitude and efficiency passes both converged on the same root-cause
observation: every `Tensor` op's `_backward` closure captures the very node
it's attached to (`out._backward = _backward`, where `_backward` references
`out`), so **every op builds a self-referential cycle**, whether or not
anything will ever call `.backward()` on the result. Phase 2 patched the
*symptom* (explicit `gc.collect()` calls in `train.py`/`generate.py`, at
three different, ad-hoc cadences) rather than the cause - and pure inference
(`generate()`, `eval_loss()`) was paying the cost of building a
fully backward-capable graph for a forward pass that never needed one.

**Fix:** `loom/tensor.py` now has a `no_grad()` context manager (the same
pattern as `torch.no_grad()`). Every primitive op checks a module-level flag
and, when disabled, returns a plain `Tensor(data)` - no `_children`, no
`_backward` closure, so there's no cycle to collect in the first place, not
just one that gets swept up faster. `generate()` and `train.py`'s
`eval_loss()` (neither ever calls `.backward()`) now run under `no_grad()`,
and their old `del`/`gc.collect()` workarounds were removed since they're no
longer needed - not because they're now redundant with a mightier hammer,
but because there's nothing left for `gc.collect()` to clean up.

Measured effect (300-token generation against the real Shakespeare
checkpoint, greedy decode): peak RSS **178MB -> 45MB** (~4x less), wall time
19.6ms/token -> 15.6ms/token (~20% faster) - and output is byte-for-byte
identical (verified: same seed, same prompt, same sampled text before and
after). The training loop's per-step forward pass still needs a real graph
(it does call `.backward()`), so it keeps its explicit `gc.collect()`.

`softmax()`/`log_softmax()` construct one hand-derived backward closure
(the numerically-stabilizing max-subtraction) that isn't a composition of
`Tensor` primitives, so it needed the same `no_grad()` check added directly
- otherwise attention's internal softmax call would have kept building a
graph even inside `no_grad()`. Verified with
`test_softmax_under_no_grad_matches_normal_softmax`.

## Cleanup (fixed)

- **`Module.parameters()` and `Module._named_params()` were two independent
  copies of the same `__dict__` tree-walk** (Tensor / Module / list-of-Module),
  one flat, one named. A future submodule container type only had to be
  taught to one of them to silently desync what the optimizer trains from
  what `state_dict()` saves. `parameters()` is now `[t for _, t in
  self._named_params()]` - one traversal, not two.
- **`softmax()`/`log_softmax()` duplicated an identical "shift" node**
  byte-for-byte. Factored into a shared `_stable_shift(x, axis)` so a future
  stability fix can't be applied to one and missed on the other.
- **`Adam.zero_grad()` (sets `grad = None`) disagreed with
  `Tensor.zero_grad()`/`Module.zero_grad()` (used to set `grad =
  np.zeros_like(data)`).** `Adam.step()` skips params whose grad `is None`;
  if a caller ever reached for `model.zero_grad()` instead of
  `opt.zero_grad()`, a parameter that received no gradient would stop being
  skipped and would instead take a zero-magnitude update that still touches
  Adam's momentum state. Unified on the `None` convention. Regression test:
  `test_module_zero_grad_matches_optimizer_zero_grad`.
- **`Tensor.detach()` and `Tensor.swapaxes()` were dead code** - confirmed
  via grep, zero call sites anywhere in `loom/` or `tests/`. Deleted rather
  than kept as untested, unverified public API surface.
- **`BPETokenizer.encode()` recomputed a `{pair: rank}` dict from scratch on
  every call**, even though `self.merges` is immutable after `train()`/
  `load()`. Now cached once as `self._ranks` at the point where `merges` is
  set, instead of rebuilt per call (relevant for `loom chat`'s REPL loop,
  which calls `encode()` once per turn).

## Explicitly deferred (documented, not fixed)

These were real findings, but fixing them would add complexity out of
proportion to their actual, measured impact at this project's scale - fixing
them anyway would itself be the kind of premature engineering this project's
guidelines warn against.

- **BPE `train()` rescans the whole corpus on every merge** (`O(num_merges x
  unique_words)` instead of only touching words affected by the last merge).
  Measured cost at the shipped scale (vocab_size=512 over the full 1.1MB
  corpus): ~10s. A real bottleneck only appears at much larger vocab sizes
  (thousands of merges) that this project doesn't use.
- **`np.add.at` (used in the embedding gradient's scatter-add) is a known
  slow, unvectorized NumPy path.** True, but profiling showed matmuls
  dominate a training step's cost by a wide margin at this model size (see
  Phase 2's training run: ~1.3s/step at 506K params, 4 layers) - vectorizing
  the scatter-add wouldn't move the needle enough to justify the added
  complexity.
- **`Adam.step()` allocates fresh arrays each step instead of updating
  `self.m`/`self.v` in place.** Real, minor allocator churn; not the
  bottleneck (see above).
- **JSON save/load logic is hand-rolled at 4 call sites** (`tokenizer.py`,
  `train.py` x3, `viz.py`) instead of one shared helper. Genuine minor
  duplication, but each site's error-handling needs are already slightly
  different (e.g. `viz.py` treats a missing `history.json` as "no history
  yet," `load_checkpoint` treats a missing `config.json` as a hard error) -
  a shared helper would need parameters for that anyway, for little real
  gain across just 4 sites.
- **`MultiHeadAttention` exposes its attention weights to `viz.py` via a
  plain `self.last_attn` side attribute**, set as a side effect of
  `__call__`, rather than a proper return-value/hook contract. This is a
  real fragility (it'd silently show the wrong weights if a module were ever
  invoked more than once per visualization pass), but a proper hook
  mechanism is speculative generality for a single internal consumer that,
  today, only ever calls each block exactly once per visualization. Noted
  for whoever adds KV-caching or batched multi-prompt visualization next.
- **Per-token `decode()` calls in `viz.py`** (used to label attention-heatmap
  axes and PCA scatter points) can render `U+FFFD` for a token whose bytes
  are only a valid *partial* UTF-8 character in isolation - this happens for
  legitimately-trained tokens on non-ASCII corpora, not just adversarial ids.
  Tiny Shakespeare is ~100% ASCII, so this doesn't manifest in the shipped
  checkpoint's visualizer; flagged here so a future corpus swap doesn't
  quietly serve confusing labels without anyone knowing why.

## Not a bug (checked, ruled out)

- Weight tying (`GPT`'s output head reuses `tok_emb.weight`) round-trips
  gradients correctly through the shared graph node - verified against
  finite-difference gradients directly on the tied weight.
- `GPT.pos_emb` (a direct `Tensor` attribute on `GPT`, not nested in a
  submodule) round-trips through `state_dict()`/`load_state_dict()`
  correctly - it's covered by `_named_params()`'s direct-attribute branch,
  not just the submodule-recursion branch.
- The BPE pre-tokenization regex (`\w+|[^\w\s]+|\s+`) is a complete,
  non-overlapping partition of any string with no hardcoded special cases -
  arguably more general than GPT-2's reference tokenizer, which hardcodes a
  list of English contractions.
- No CLAUDE.md violations found (checked repo-root `.claude/CLAUDE.md`
  against every new file: dated folder, README inside it, LEDGER.md
  deferred to the final ship commit as every other project in this repo
  does - none of these are violations of the stated rules).

## Gate

Fresh run-through after all fixes: `python3 -m pytest tests/` -> **63/63
passing** (was 44 before this phase; +19 regression tests, one for every
confirmed bug above), the real Shakespeare checkpoint still generates
byte-for-byte identical output at a fixed seed before/after the `no_grad()`
refactor, and the visualizer was re-verified in a real headless Chromium run
with zero console errors on both the normal checkpoint and the new 0-layer
edge case.
