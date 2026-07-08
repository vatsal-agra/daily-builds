# Adversarial Review

Reviewed as a hostile reviewer: hunted for bugs, broken edge cases, ugly UX,
and lazy shortcuts across the autograd engine, transformer modules,
tokenizer, training loop, CLI, chat REPL, and attention visualizer. Every
finding below was fixed and given a regression test (or, for the false
alarm, documented so the record is honest about what *wasn't* a bug).

## Critical

**1. Reference-cycle memory blow-up in the autograd engine (OOM-killed a real
training run).** Every op's backward closure captures its own `out` (to read
`out.grad`), producing `out._backward -> closure -> out`, a genuine
reference cycle. Python's refcounter can't free cycles; only the
generational cyclic GC can, and during a training loop that builds a fresh
graph every step, it visibly can't keep up -- a benchmark run with a modest
model (875K params) grew past the container's memory limit and was
SIGKILLed (exit 137) after only a handful of steps. Fixed by explicitly
breaking `_backward`/`_prev` links on every **non-leaf** graph node right
after `backward()` completes, so refcounting reclaims the graph immediately
instead of waiting on the cyclic collector (`tensor.py::backward`). Verified
with `test_graph_nodes_freed_after_backward` (a `weakref` + single
`gc.collect(0)`, i.e. *no* generational collection needed, must free the
node) and confirmed a subsequent real training run holds steady at ~2.7 GB
peak RSS instead of climbing toward the earlier ~11 GB / OOM.

**2. The first fix broke leaf parameter reuse across training steps.** My
first pass at fix #1 cleared `_backward`/`_prev` on *every* node in the
backward traversal, including leaf/parameter tensors -- but parameters
persist across training steps (they're not per-step temporaries) and get
re-used as children in every new step's graph. Nulling their harmless
default `_backward` broke the very next `loss.backward()` call with
`TypeError: 'NoneType' object is not callable`. Fixed by only clearing
nodes that actually have children (`if v._prev:` -- true only for real op
outputs, never for leaves, since leaves are created with an empty
`_children`). Caught before it ever reached a real training run, by writing
a regression test first (`test_leaf_reused_across_multiple_backward_graphs`)
that simulates exactly this training-loop pattern.

## Real bugs

**3. BPE `decode()` crashed on an undertrained/sampled token sequence.**
Generating from a barely-trained model raised
`UnicodeDecodeError: 'utf-8' codec can't decode byte ... invalid
continuation byte` -- an arbitrary (as opposed to `encode()`-produced) token
ID sequence has no guarantee its concatenated bytes land on valid UTF-8
boundaries. Fixed by defaulting `decode(ids, errors="replace")`, the same
convention real BPE tokenizers (GPT-2's included) use; `encode()` output
still round-trips byte-exact regardless, since it always produces
well-formed UTF-8 by construction. Regression test:
`test_decode_never_crashes_on_invalid_byte_boundaries`.

**4. Streaming chat could garble a multi-byte character split across two
adjacent tokens.** A first draft decoded each generated token's bytes in
isolation and concatenated the resulting strings -- but a BPE token's raw
bytes aren't guaranteed to be a complete UTF-8 character on their own; a
2-4 byte character can straddle a token boundary, and naive per-token
decoding would occasionally emit a stray U+FFFD mid-word. Fixed by feeding
each token's raw bytes through a stdlib incremental UTF-8 decoder
(`codecs.getincrementaldecoder`), which correctly buffers an incomplete
trailing byte sequence until the rest arrives. Regression test:
`test_split_multibyte_character_decodes_correctly`.

**5. Missing/untrained checkpoint gave a raw, confusing traceback.**
`cli.py generate --checkpoint-dir <typo-or-missing-dir>` surfaced a bare
`FileNotFoundError` pointing at an internal `config.json` path with no
indication of what to do about it. Fixed with an explicit existence check
in `load_checkpoint` that names the missing files and suggests
`cli.py train`, plus a top-level `try/except` in `cli.py:main()` that prints
`error: ...` and exits 1 for user-facing input errors instead of a
traceback. Regression test: `test_missing_checkpoint_gives_clean_error_not_traceback`.

**6. Silent no-op when a KV-cached generation request can't be satisfied.**
Position embeddings only cover `[0, block_size)`, so a prompt already at or
past `block_size` combined with `use_kv_cache=True` silently returned the
prompt unchanged with zero new tokens -- correct, but with no explanation, a
real "why didn't this do anything" trap for a caller. Fixed with a
`RuntimeWarning` naming the requested vs. available token budget and
suggesting `use_kv_cache=False` for the sliding-window path. Regression
tests: `test_generate_warns_when_prompt_already_exceeds_block_size`,
`test_generate_no_warning_when_kv_cache_disabled` (asserts the *non*-cached
path, which has no such limitation, never warns).

## Code-quality / lazy-shortcut cleanup

**7. Attention visualizer duplicated the real forward-pass logic instead of
capturing it.** An early draft of `viz.py` monkey-patched
`CausalSelfAttention.forward` with a hand-copied re-implementation just to
stash the attention weights -- a maintenance hazard (two copies of the same
math that can silently drift apart) and exactly the kind of shortcut the
build rules call out. Fixed by having `CausalSelfAttention.forward` itself
stash `self.last_attn` as a normal, cheap side effect of the one real
implementation; the visualizer just reads it off each block after an
ordinary forward pass. No duplicated logic, and `test_captured_attention_is_causal`
verifies the captured weights are the real thing (exactly zero above the
diagonal, every row sums to 1).

**8. Dead code.** An unreachable `if prompt_ids.shape[1] == 0` fallback in
`generate.py` (impossible after the preceding empty-prompt substitution,
since `encode()` of any non-empty string always yields >=1 token -- the
pretokenizer regex partitions every character into word/whitespace/other,
with no gaps) and a no-op `if not use_kv_cache: pass` in `GPT.generate`.
Both removed.

## Checked and confirmed correct (no bug found)

- **Multi-axis `sum(axis=(...))` backward.** No test exercised the
  multi-axis-tuple path directly. An ad hoc numerical check first
  *appeared* to show a large gradient mismatch -- but that was a bug in the
  throwaway verification script itself (its closure captured the wrong
  array object, so the "numeric" side was measuring a constant function).
  Redone correctly (matching the same pattern the real test harness uses),
  the gradient matches to 1e-9. Recorded honestly here rather than silently
  discarded, and promoted to a permanent regression test
  (`test_sum_multi_axis_tuple`) since the path had no prior coverage.
- Causal masking: verified both structurally (attention weights are exactly
  zero above the diagonal at every layer/step, `test_captured_attention_is_causal`)
  and behaviorally (perturbing a future token never changes any earlier
  position's output, `test_future_token_never_affects_past_output` /
  `test_middle_perturbation_only_affects_itself_and_later`).
- KV-cache: verified numerically identical logits vs. the non-cached path,
  both for the primed-prompt step and the first incrementally-decoded token
  (`test_kv_cache_matches_full_forward`).
- Tokenizer round-trip: exact on training text, unseen text, unicode/emoji,
  and the empty string; deterministic across independent training runs;
  never merges a pair that occurs only once.
- Generation edge cases stress-tested directly (not just through the CLI):
  prompt length exactly equal to `block_size`, prompt longer than
  `block_size`, `temperature=0`, `top_k=1` -- none crash.
- Checkpoint round-trip gives bit-identical forward outputs before/after
  save+load, and rejects a config/weights shape mismatch instead of loading
  silently-wrong weights.

## What shipped instead of what was planned

Nothing was dropped or downsized from the required feature list. All 4
required features and all 3 planned stretch features shipped as specified
in PLAN.md.
