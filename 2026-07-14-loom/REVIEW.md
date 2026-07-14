# Adversarial review (Phase 3)

Methodology: probed every CLI entry point and library function with
malformed/edge-case input a hostile user or a careless caller would hit,
rather than only the happy path already covered by the Phase 2 test suite.
Every finding below was first reproduced with a standalone repro script,
then fixed, then covered by a regression test.

## Findings

1. **Bug — `viz.render()` crashes instead of truncating.** The visualizer
   hardcodes `max_context=48` when slicing the prompt but never clamps it to
   the model's actual `max_seq_len`. Any model trained with `max_seq_len <
   48` (or a prompt whose encoded length exceeds `max_seq_len` even when
   below 48), and the very next `model.forward()` call inside `render()`
   raises an unhandled `ValueError`. Repro: a `max_seq_len=10` model + a
   32-token prompt → crash. **Fix:** clamp `max_context = min(max_context,
   model.max_seq_len)` in `viz.render()`.

2. **Robustness gap — unescaped `</script>` in the generated HTML.** The
   visualizer embeds tokenizer output (ultimately derived from the
   `--prompt` CLI argument, i.e. attacker-influenceable input) as raw
   `json.dumps(...)` text inside a `<script>` block. `json.dumps` does not
   escape `/`, so a token sequence that happens to reconstruct the literal
   substring `</script>` would prematurely close the script block and let
   the rest of the "JSON" be interpreted as HTML/script — the exact class of
   bug a previous daily build (Palimpsest, 2026-07-04) shipped and had to
   patch. Not currently triggerable by the bundled Shakespeare corpus (BPE
   never learns a `</script>`-shaped merge from it), but a `--prompt`
   argument is user input and this is cheap to close as defense in depth.
   **Fix:** escape `</` as `<\/` in the embedded JSON before writing the
   HTML.

3. **UX bug — raw Python tracebacks on ordinary bad input.** None of the
   common, entirely foreseeable misuse paths were caught at the CLI
   boundary: a missing corpus file, a missing checkpoint directory, a
   `--vocab-size` under 256, an `n-heads` that doesn't divide `d-model`, and
   an empty corpus file all dumped a full Python stack trace instead of a
   one-line error. This is the same category of issue flagged and fixed in
   several previous daily builds (Cryptex, Ironkey, VecNN). **Fix:** wrap
   `cli.py`'s `main()` so `ValueError`/`FileNotFoundError`/`KeyError` print
   `error: <message>` to stderr and exit 1; everything else still surfaces
   as a real traceback (a genuine bug shouldn't be hidden).

4. **Minor bug — `viz`/checkpoint writes don't create missing parent
   directories.** `cmd_viz --out somedir/viz.html` (where `somedir/` doesn't
   exist yet) crashed with `FileNotFoundError` even though `train()` already
   does the equivalent `os.makedirs(..., exist_ok=True)` for its own output
   directory. **Fix:** create the parent directory before writing in
   `viz.render()`.

5. **Lazy shortcut — `cmd_demo` fabricates fake argparse namespaces.** It
   built throwaway empty classes (`class A: pass; a = A(); a.foo = ...`) to
   reuse the `cmd_*` functions instead of the obvious `argparse.Namespace`.
   Functionally harmless but exactly the kind of shortcut this phase exists
   to catch. **Fix:** replaced with `argparse.Namespace(...)`.

6. **Test-coverage gap — the visualizer had zero tests.** Finding #1 above
   was a basic, easily-scriptable case that a single test would have caught
   before it ever reached "shipped" status. **Fix:** added
   `tests/test_viz.py` covering: normal rendering, a prompt/model combo that
   previously crashed (regression test for #1), the `</script>`-adjacent
   payload (regression test for #2), missing-parent-directory output paths
   (regression test for #4), and rendering with/without a training log
   present.

## Things checked and found *not* to be bugs

- `d_model % n_heads != 0` was already rejected with a clear `ValueError`
  (just needed to not leak as a traceback — see #3).
- BPE tie-breaking between equally-frequent pairs is deterministic (verified
  by training twice on the same corpus and diffing the learned merge list).
- `vocab_size == 256` (zero learned merges) trains and round-trips
  correctly — falls back to pure byte-level tokens.
- No pathological long whitespace runs in the bundled corpus that would make
  the O(word_length²) per-word BPE merge-application slow.
- Causal masking, seq_len=1, and batch_size=1 are all gradient-checked and
  behave correctly (already covered in Phase 2's test suite).
- Nucleus (top-p) and top-k sampling behave correctly at their boundary
  values (`top_p` at/above 1.0, `top_k` at/above vocab size) — both degrade
  to a no-op rather than erroring.
- Demo-scale generations (2-layer, d_model=64, 300 steps) visibly learn
  corpus *structure* — character-name-then-dialogue formatting, colons,
  capitalization patterns — but not real English words yet at that tiny
  scale/step count. The README states this honestly rather than
  cherry-picking a longer run's output, the same mistake a previous ledger
  entry (Cotangent) called out in its own review.
- Resuming training from an existing checkpoint is *not* supported — running
  `train` twice into the same `--out` directory silently starts a fresh
  model rather than continuing the old one. This is a deliberate scope
  decision (checkpointing exists for inference/viz, not resumable training),
  not a bug, and is noted in the README's limitations.
