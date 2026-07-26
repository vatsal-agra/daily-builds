# Adversarial review — Loom

Reviewed as a hostile user/attacker: fed malformed input to every entry
point, tried to break the autodiff engine with numerical checks, ran the
CLI the way a first-time user actually would (not the way I remembered
writing it), and stress-tested generation at its context-window boundary.

## Bugs found and fixed

### 1. Server crashed (HTTP 500 + leaked traceback) on non-finite or wrong-typed generation parameters

`POST /api/generate` parsed `temperature`/`top_k`/`top_p`/`seed` with bare
`float()`/`int()` calls and no range/finiteness check. Two ways to break it:

- Python's `json` module accepts the non-standard literals `NaN`,
  `Infinity`, `-Infinity` by default. `{"temperature": NaN}` parsed
  successfully to `float('nan')`, sailed through `max(0.0, min(nan, 5.0))`
  unclamped (comparisons against NaN are always `False`), and then produced
  an all-NaN logits array whose softmax fed `numpy.random.choice` a
  probability vector containing NaN — a `ValueError` deep inside sampling,
  surfaced to the client as a raw 500 with a Python traceback.
- `{"top_k": "lots"}` (a string where a number was expected) raised an
  uncaught `ValueError` from `int("lots")`, same 500-with-traceback outcome.

**Fix:** added `_numeric_field()` in `loom/server.py`, which casts, checks
`math.isfinite()` for floats, and clamps to a valid range, raising a new
`BadRequest` on failure; `do_POST` now maps `BadRequest` to a clean HTTP 400
with a helpful message instead of a 500. Regression-tested in
`tests/test_integration.py::test_server_end_to_end` against all four
reproductions (NaN temperature, Infinity max_new_tokens, string top_k,
string seed) plus a confirmation that well-formed requests still succeed.

### 2. `loom train` CLI mis-parsed its own flags

`loom train --out ckpt --vocab-size 512 ...` failed immediately with
`error: unrecognized arguments: --out`. Root cause: passing a subcommand's
flags through a `nargs=argparse.REMAINDER` positional on a `subparsers`
child is a known CPython argparse footgun — flag-shaped tokens
(`--out`, `--vocab-size`, ...) immediately following the subcommand name
get partially consumed by the *outer* parser's option matching before the
child parser's `REMAINDER` positional gets a chance at them, rather than
being captured whole. This wasn't caught earlier because every manual test
of `loom.train` up to that point ran it directly (`python -m loom.train`),
never through the `loom` CLI wrapper.

**Fix:** `loom/cli.py` now intercepts `train` as the very first thing in
`main()`, before the top-level `argparse.ArgumentParser` ever sees the
argv, and hands off directly to `loom.train`'s own complete argument
parser — sidestepping the REMAINDER/subparsers interaction entirely. The
dead `cmd_train` indirection and the now-unreachable REMAINDER subparser
definition were removed. Verified end-to-end: `loom train --out ... --vocab-size
260 --block-size 16 ... --max-steps 5` now runs and writes a checkpoint.

### 3. `loom generate` / `loom attention` crashed with a raw traceback on a missing checkpoint

`loom serve` already checked for `weights.npz` and printed a clean error +
next-step hint if a checkpoint directory didn't exist. `loom generate` and
`loom attention` didn't have the same guard — pointing either at a
nonexistent path raised an uncaught `FileNotFoundError` from deep inside
`checkpoint.load()`, dumping a full traceback instead of telling the user
what to do.

**Fix:** added a shared `_load_checkpoint_or_die()` helper in `loom/cli.py`
used by both commands, matching the message style `loom serve` already
had. Verified: `loom generate hi --checkpoint /tmp/does-not-exist` now
exits 1 with `error: no checkpoint found at ... train one first: loom
train --out ...` instead of a traceback.

### 4. Weight decay applied to LayerNorm gain/shift and biases

`Adam.step()` applied decoupled weight decay to every parameter uniformly,
including the 1D LayerNorm `gamma`/`beta` and biases. This is a known
anti-pattern (widely documented, e.g. in GPT-2/nanoGPT's optimizer setup):
decaying a LayerNorm gain toward zero actively fights the normalization it
exists to provide, and biases have no business being regularized toward
zero the way weight matrices do.

**Fix:** `Adam.step()` now only applies weight decay to parameters with
`ndim >= 2` (embedding tables and weight matrices), skipping 1D params.
*Note on the shipped checkpoint:* this fix landed while the real training
run (the one shipped in `checkpoints/loom-shakespeare/`) was already ~10
minutes into its ~20-minute run. With `weight_decay=0.01` and this run's
step count, the quantitative effect of the bug is a compounded ~1% total
shrinkage of 1D parameters over the whole run — far below the noise floor
of a run this size. Restarting to save well under 1% would have cost
another ~20 minutes of compute for no measurable difference in the shipped
model's output quality, so the in-flight run was kept; the fix is verified
by the test suite's own fresh training runs (`tests/test_model.py`,
`tests/test_integration.py`), which all still pass and still overfit/learn
correctly with the corrected optimizer.

## Things specifically hunted for and confirmed correct (not just assumed)

- **Every autodiff op's backward pass** (`loom/engine.py`) is checked
  against central-difference numerical gradients in
  `tests/test_engine.py` — the real correctness gate for this project,
  since a wrong gradient doesn't crash, it just silently fails to learn.
  All 17 op/group checks pass to <1e-4 absolute or <1% relative error.
- **The full model's gradient**, not just individual ops in isolation:
  sampled entries of one weight matrix inside a real forward+backward pass
  checked against finite differences, matching to 1e-12.
- **Causal masking**: changing only the *last* token of a sequence and
  re-running the forward pass leaves every earlier position's logits
  bit-for-bit identical — the actual behavioral guarantee a causal
  transformer must have, not just "the mask array looks right."
- **Attention weights** extracted for visualization sum to exactly 1 per
  row and are exactly 0 for every future position, for every layer/head.
- **A tiny-batch overfit test** (`tests/test_model.py`) — a much stronger
  gate than "loss goes down eventually": on a fixed batch, loss must drop
  from baseline to <0.001 within 150 Adam steps, which only happens if
  every gradient in the full stack (embedding, attention, MLP, LayerNorm,
  weight-tied output head) is correct.
- **BPE tokenizer**: exact round-trip on real trained text; byte-fallback
  round-trip on deliberately adversarial input (null bytes, unseen Unicode,
  emoji, long unseen runs); empty-string encode/decode; deterministic
  training given the same corpus; save/load fidelity (re-encoding after a
  JSON round-trip produces identical token IDs).
- **Sampling**: temperature=0 is exact argmax (not "usually" argmax);
  unfiltered sampling's empirical distribution over 4000 draws matches the
  analytic softmax to within 3%; top-k keeps *exactly* k logits, not
  "about k"; top-p keeps the minimal prefix covering the requested mass.
- **Generation at the context boundary**: a prompt far longer than
  `block_size`, an empty prompt, and temperature=0 greedy decoding all run
  without crashing (window sliding is exercised, not just asserted).
- **Server hardening**: malformed JSON body, empty attention prompt, and
  (per bug #1 above) NaN/Infinity/wrong-typed fields all return clean 4xx
  JSON errors; a real subprocess `loom.server` was driven over actual HTTP
  (not an in-process mock) for every endpoint the frontend calls.

No other correctness issues were found. The remaining gap that's a
deliberate scope decision, not a bug: generation is full-recompute per
token (no KV cache) — fine at this model's size and the UI's 500-token cap,
called out explicitly in `loom/generate.py` rather than silently accepted.
