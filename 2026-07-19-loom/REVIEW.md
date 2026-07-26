# Adversarial review — Loom

Hostile self-review of the autodiff engine, model, training pipeline, CLI,
tokenizers, and attention visualizer, done while the full training run was
in progress in the background (so review time wasn't wasted waiting).

## Real bugs found and fixed

1. **`Tensor.backward()` crashed whenever a non-differentiable leaf fed into
   a differentiable op** (e.g. `x / const_tensor`, since division is built
   from `mul` + `pow(-1)` on the constant). The topological sort visits
   every node reachable from the output, including ones with
   `requires_grad=False`, but `backward()` unconditionally called every
   node's local `_backward()` closure — which reads `out.grad`, and for a
   non-requiring-grad node that value was never set (its `_accum` short-
   circuits). First real op this broke was `div` in `gradcheck.py`.
   **Fix:** only call `v._backward()` for nodes with `requires_grad=True`
   (`loom/tensor.py`). Caught immediately by the gradient-check suite before
   any model code was written on top of it.

2. **`generate(..., return_attn=True)` crashed on a BPE-tokenized model.**
   It called `tokenizer.itos[i]` directly to label frames for the
   visualizer — an attribute that only exists on `CharTokenizer`.
   `BPETokenizer` has no `.itos`. **Fix:** added a `token_str(id)` method to
   both tokenizer classes and switched `generate.py` to call that instead.

3. **Empty-prompt generation seeded with raw token id `0`.** For
   `CharTokenizer` that's just whatever character sorts first in the
   corpus's vocabulary (harmless), but for `BPETokenizer` id `0` is the raw
   byte `0x00` — a null byte would open every unprompted generation.
   **Fix:** prefer encoding a plain space as the seed (valid and printable
   under either tokenizer), falling back to id `0` only if the corpus
   genuinely never contained a space (exercised in
   `tests/test_generate.py`).

4. **`CharTokenizer.encode` raised a bare `KeyError` on any character absent
   from the training corpus** (e.g. a user prompt containing a digit or
   symbol the corpus never used) — no indication of *which* character or
   why. **Fix:** raise a `ValueError` naming the offending character(s).

5. **The attention visualizer's embedded JSON could break out of its
   `<script>` block.** Generated text is arbitrary model output; if it ever
   contained the literal sequence `</script>` (plausible if the model were
   retrained on HTML-ish text), the unescaped `</` would close the
   `<script>` tag early and inject markup into the surrounding page — the
   same class of bug a previous ledger project (Palimpsest, 2026-07-04)
   flagged as its worst finding. **Fix:** escape `</` to `<\/` in the JSON
   payload before embedding it (`loom/attn_viz.py`), with a regression test
   asserting a `</script><img onerror=...>` payload can't survive intact.

6. **`attn_viz.render()` and `save_checkpoint()` crashed with
   `FileNotFoundError` if their output directory didn't exist yet** — fine
   for the CLI (which pre-created directories) but not for direct library
   use, and the CLI's JSON-dump branch of `cmd_attn` was missing the same
   directory creation the HTML branch got. **Fix:** both library functions
   now create their own output directory; removed the now-redundant
   `os.makedirs` from `cmd_train`.

7. **`DEFAULT_CKPT` didn't match the checkpoint-file convention actually
   used to train and ship `checkpoints/loom`.** The CLI's built-in default
   was `checkpoints/loom.npz`, which — because `save_checkpoint` always
   derives its metadata filename by appending `.json` to whatever path it
   was given — would have looked for `checkpoints/loom.npz.json` while the
   real shipped file is `checkpoints/loom.json`. Running the documented
   quickstart commands with no `--ckpt`/`--out` override would have failed
   to find the metadata file. **Fix:** changed `DEFAULT_CKPT` to
   `checkpoints/loom` (no suffix), matching every other reference to the
   shipped checkpoint in `demo.sh` and the README.

8. **Only the final training step's weights were ever saved**, even though
   validation loss on this small, 17.7 KB corpus peaks early (best around
   step 600 of 4000) and then rises as the model starts memorizing the
   training windows — a completely expected outcome for a from-scratch
   model on a tiny corpus, but shipping the *last* checkpoint regardless
   meant shipping a needlessly more-overfit model than necessary. **Fix:**
   `train.py` now tracks the best validation-loss checkpoint during
   training and restores those weights before saving, alongside adding
   dropout (0.1) to the model itself to push best-val-loss later into
   training. **Confirmed against the real completed run:** with dropout,
   validation loss still peaked early (best 1.7915 at step 600 of 4000;
   train loss kept falling to 0.40 by step 4000 while val loss drifted up
   to ~2.8) — dropout alone can't fix a corpus this small, so the
   best-checkpoint tracking is doing real, necessary work, not guarding
   against a hypothetical. The shipped `checkpoints/loom.npz` is the
   step-600 snapshot.

9. **Every CLI subcommand printed a raw Python traceback on any expected
   error** (missing checkpoint file, an out-of-vocabulary prompt character,
   a corpus too short for the requested `--block-size`, a bad
   `--d-model`/`--n-heads` combination) — functionally correct (the errors
   above are already real, informative exceptions) but a poor CLI
   experience, and exactly the "raw tracebacks on malformed input" pattern
   flagged as a real bug in more than one earlier ledger project. **Fix:**
   `cli.main()` now catches `ValueError`/`FileNotFoundError` at the top
   level and prints a clean `Error: ...` message with exit code 1 instead
   of a stack trace (`tests/test_cli.py` locks this in for all four cases
   above via subprocess).

## Dead code removed

- `Tensor.zero_grad()`, `Tensor.zeros()`, `Tensor.constant()` — none were
  ever called anywhere in the codebase or tests (`Adam.zero_grad()` sets
  `p.grad = None` directly; nothing else needed a zero/constant factory).
- `colorFor()` in the attention-visualizer JS was defined and never called
  — `drawHead()` had its own inline, duplicate color-ramp math for
  `ImageData` pixels (which need raw numbers, not the CSS string
  `colorFor` produced). Removed the unused function rather than force a fit.

## Hardening (not bugs, but worth doing before shipping)

- `MultiHeadAttention.__init__` raised a bare `AssertionError` on a
  `d_model` not divisible by `n_heads` — replaced with a `ValueError`
  naming both values, since this is a totally plausible CLI typo
  (`--d-model 65 --n-heads 4`) and deserves a real message.
- `loom attn -n <large>` embeds one full layer×head×context² attention
  matrix per generated token as JSON in the output HTML; with a long
  generation this becomes a very large, slow file. Added a warning above a
  configurable threshold rather than silently producing a multi-hundred-MB
  page.

## Verified, not just asserted

- Every one of the 26 autodiff ops has an independent numerical
  finite-difference gradient check (`loom/gradcheck.py`), plus a
  full-model end-to-end check that perturbs real weights inside a real
  forward pass through the whole transformer and compares against the
  same numeric method (`tests/test_nn.py::test_end_to_end_gradient_check`).
- The attention visualizer's actual generated JS/HTML was smoke-tested in
  headless Chromium (`tests/test_viz_browser.py`, skips cleanly if no
  browser is available) — it loads with zero console/page errors, the
  layer selector and step controls work, and the right number of
  per-head canvases render.
- The from-scratch BPE tokenizer was checked to learn the single most
  frequent byte pair first on a controlled corpus, to round-trip losslessly
  on in-corpus, out-of-corpus, non-ASCII, and empty strings, and to
  actually shrink token count vs. raw bytes.

## What's honestly still a limitation, not a bug

- The training corpus is ~17.7 KB of original prose. A model this small,
  trained on this little text, memorizes large stretches of the training
  data rather than generalizing broadly — that's expected and disclosed,
  not hidden. The point of this build is a *correct, from-scratch*
  autodiff-and-transformer implementation, not state-of-the-art language
  modeling; the shipped checkpoint is the best-validation-loss snapshot for
  exactly this reason, not the most-memorized one.
- The from-scratch BPE `encode()` is O(n² log n) per call (recomputes pair
  counts and takes a `min` over them every merge step) — fine for prompts
  and this corpus size, would need a priority-queue rewrite to scale to
  much longer documents.
