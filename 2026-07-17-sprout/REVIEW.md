# Adversarial review

Hostile pass over Sprout looking for crashes, bad edge-case behavior, and
lazy shortcuts. Each issue found was reproduced first, then fixed; a fresh
run-through after the fixes hits none of them (see the reproduction
commands below — they now behave correctly).

## Issues found and fixed

### 1. `train.py --steps 0` (or negative) silently produces a broken checkpoint

**Repro:** `python3 train.py --steps 0` runs the training `for` loop zero
times, so `history["train_loss"]`/`history["val_loss"]` stay empty lists.
The checkpoint still saves "successfully." Any downstream tool that reads
`history["train_loss"][-1]` (`model_card.py`) then dies with an
`IndexError` far away from the actual mistake, and `generate.py` would
silently sample from a randomly-initialized, completely untrained model
with no warning that nothing was ever trained.

**Fix:** `train.py` now validates `args.steps >= 1` up front and exits with
a clear message instead of proceeding.

### 2. Missing checkpoint = raw Python traceback in three of the four entry points

**Repro:** `python3 server.py` (or `attention_viz.py`, or `model_card.py`)
with no checkpoint present crashes with an unhandled `FileNotFoundError`
traceback pointing into `pickle.load`. `generate.py` already handled this
case with a friendly message ("No checkpoint found... Run train.py
first.") — the other three entry points didn't get the same treatment,
which is exactly the kind of inconsistency a hostile pass exists to catch.

**Fix:** `attention_viz.py`, `model_card.py`, and `server.py` now all catch
`FileNotFoundError` around `load_checkpoint` and print the same style of
actionable message before exiting, matching `generate.py`.

### 3. `server.py` shared a single `numpy.random.Generator` across request threads

**Repro:** `server.py` uses `ThreadingHTTPServer`, so two browser tabs
hitting "Generate" at the same moment run on two different threads. Both
were calling `sample(..., rng=self.rng)` against the *same* `Generator`
instance stored on the `Handler` class with no locking. `Generator` methods
are not documented as thread-safe; concurrent mutation of its internal
state from two threads is a real (if narrow) race condition — not a
theoretical one, since a from-scratch demo server is exactly the kind of
thing someone opens in two tabs at once.

**Fix:** each `/generate` request now creates its own
`np.random.default_rng()` instead of touching shared mutable state, which
is both simpler and correct under concurrency.

### 4. `filter_logits` top-p path used an O(vocab) Python-level loop

Not a correctness bug, but a lazy-shortcut smell worth calling out: the
top-p filter rebuilt the "keep" mask with a `for i in range(vocab_size):
... if i not in keep_idx` Python loop and a Python `set`, when the whole
thing is a boolean mask operation NumPy already does natively. At Sprout's
vocab size (512) this never mattered for correctness or speed, but it's
exactly the kind of code that becomes an actual bottleneck the moment
vocab size grows, and there's no reason to write it the slow way.

**Fix:** rewritten as a vectorized boolean mask (`np.full(..., True)`,
scatter `False` at the kept indices via fancy indexing, `np.where`).

### 5. Corpus generator could pick the same animal/character on both sides of a sentence

**Repro (caught before the first real training run, fixed then, listed
here for completeness):** `data/make_corpus.py`'s `fill()` originally used
independent `random.choice()` calls for `{an1}`/`{an2}` and `{c1}`/`{c2}`,
so sentences like "A wren and a wren shared the same stretch of bank..."
were possible — ungrammatical-reading and a sign of low care in a corpus
that's supposed to demonstrate real repeatable structure.

**Fix:** switched to `random.sample(..., 2)` so the two picks in a
template are always distinct.

## Things checked that turned out fine (no fix needed)

- Every module's backward pass — `gradcheck.py` compares analytic gradients
  against finite differences for every parameter in `Linear`, `LayerNorm`,
  `Embedding`, `CausalSelfAttention`, `MLP`, `Block`, and the full `GPT`
  model (28+ individual checks). All pass with relative error under 1e-4
  (most under 1e-7).
- Untrained-model sanity check: initial training loss is 6.256 nats,
  and `ln(vocab_size=512) = 6.238` — a freshly-initialized model that
  hasn't learned anything should produce close to uniform predictions,
  and it does. This is an independent, non-gradient-based correctness
  signal for the loss/softmax implementation.
- Tokenizer: empty-string encode/decode, unicode round-trip (including
  4-byte codepoints and characters never seen during BPE training),
  save/load round-trip, `vocab_size < 256` rejected, degenerate
  single-character and zero-merge corpora.
- Generation: temperature exactly 0 (greedy, deterministic across runs
  with the same seed), negative temperature (also treated as greedy — a
  defensible choice, not undefined behavior), `top_k` far larger than the
  vocabulary, `top_p` at the 0.0/1.0 boundaries, empty prompt, prompt made
  entirely of characters absent from the training corpus (still encodes
  and generates via byte-level fallback), generation requested well beyond
  `block_size` (correctly uses a sliding context window).
- `train.py get_batch` on a corpus shorter than `block_size` raises a
  clear `ValueError` instead of an out-of-bounds crash or a silent
  wrong-shape batch.
- Checkpoint round-trip: save then load reproduces bit-identical forward
  pass output and identical tokenizer behavior.
- Malformed HTTP requests to `server.py` (bad JSON, missing
  `Content-Length`) return a `400` with an error message instead of
  crashing the server process.

All 22 unit tests plus `gradcheck.py` still pass after the fixes above
(re-run in Phase 5's verification pass).
