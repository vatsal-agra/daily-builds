# Adversarial review

Hostile pass over Loom after Phase 2, hunting specifically for the kind of
bug a "it ran without crashing" smoke test would miss: silent numerical
wrongness, inconsistency between two code paths that are supposed to agree,
and edge-case crashes.

## Findings

### 1. CRITICAL — KV-cache prompt-priming skipped the causal mask entirely

`CausalSelfAttention.forward` decided whether to apply the causal mask with
`if cache is None: ...`. That's wrong: a KV-cache can be *primed* with more
than one new token at once (the whole prompt, in a single forward call,
before incremental single-token decoding begins) — and the code was
treating "a cache object was passed" as synonymous with "there is exactly
one new query token, which trivially can't see any future token." When
priming with an N-token prompt, all N of those tokens went through
self-attention with **zero masking among themselves**, so token 3 could
attend to token 7 — a real information leak that silently corrupts every
KV-cached generation whose prompt is longer than one token (i.e. every
realistic use of the KV-cache).

Caught by `tests/test_model.py::test_kv_cache_matches_full_recompute_under_greedy_decoding`,
which found that cached and non-cached greedy decoding produced different
token sequences from the same prompt — a property that must hold exactly
under masking, since both are the same math.

**Fix:** rebuilt the mask from absolute positions
(`key_pos <= pos_offset + query_index`) for every call, cache or not, T=1
or T>1. This is strictly more general than the two special cases it
replaces and there is no longer a branch that can forget to mask.
(`loom/nn.py`)

### 2. REAL BUG — generation diverged (and silently misbehaved) once the prompt reached the context window

With a prompt at or beyond `max_seq_len`, the cached path generated **zero**
new tokens (its `pos` counter started already at the window limit) while
the non-cached path generated **exactly one** token and then stopped (its
break condition checked the *unbounded* length of the full generated list,
not the windowed context actually seen by the model). Neither matched what
a user asking for N new tokens would expect, and the two paths gave
different answers to the same request.

**Fix:** the prompt is now truncated to the most recent `max_seq_len`
tokens exactly once, up front, in both paths; generation then runs for
`min(max_new_tokens, room left in the window)` steps with no further
truncation. This makes both code paths compute literally the same
sequence of forward passes for any input, which a new regression test
(`test_generate_with_prompt_longer_than_context_window`) checks directly.
(`loom/generate.py`)

### 3. Test-design pitfalls (not product bugs, logged for transparency)

Two of my own *tests* were wrong in ways that would have hidden a real
engine bug had one been present:

- The first `softmax` gradient check summed the softmax output as its
  scalar objective. Softmax rows sum to exactly 1 regardless of the input,
  so that objective's true gradient is exactly zero everywhere — the check
  couldn't have distinguished a correct backward rule from a broken one.
  Fixed by weighting the output with random weights before summing.
- The weight-tying test mutated an embedding row by adding a **uniform**
  constant to every element, then checked that logits changed. On a freshly
  initialized (untrained) model the final LayerNorm has `gamma=1, beta=0`,
  which makes its output rows exactly zero-mean by construction — and
  `dot(zero_mean_vector, constant_vector) == 0`, so the perturbation was
  invisible for a reason that had nothing to do with whether tying worked.
  Fixed by using a random (non-uniform) perturbation instead.

Both are documented here because "the test passed" and "the test would
have caught a real bug" are different claims, and the review process is
supposed to be honest about which tests actually exercise what they claim
to.

### 4. Minor — dead defensive code

`generate()` filtered `prompt_ids` with `[i for i in prompt_ids if i <
tokenizer.vocab_size]` — but `tokenizer.encode()` can never return an id
outside its own vocab by construction, so this was validating a condition
that cannot occur. Removed.

### 5. Minor — checkpoint save crashed on a fresh output directory

`save_checkpoint` called `np.savez(path + ".npz", ...)` directly; if the
parent directory of `--out` didn't already exist (true for any `--out`
other than the one committed to this repo), it raised `FileNotFoundError`
instead of just creating the directory like every other artifact-writing
command in this project does. Fixed with `os.makedirs(..., exist_ok=True)`.

## Hostile testing performed (no issues found)

- **Server robustness**: malformed JSON body, empty body, negative
  `max_new_tokens`, `max_new_tokens=999999`, empty-string `/api/attention`
  text, unknown routes — every case returns a clean 4xx with a JSON error
  body or a sane clamp, never a raw traceback to the client.
- **BPE on pathological input**: repeated-character runs (`"aaaaaaaa
  bbbbbbbb"`) merge in the textbook non-overlapping left-to-right order
  and round-trip exactly; empty string; emoji/unicode; text far outside
  the training distribution.
- **Numerical**: every autograd op gradient-checked against finite
  differences (not just "the loss went down"); non-finite gradients
  checked-for explicitly after a real backward pass through the full model.
- **Concurrency**: the playground server is a `ThreadingHTTPServer`;
  `generate()` allocates its own KV-cache per call and inference never
  mutates model weights, so concurrent requests can't corrupt each other's
  state.

## Outcome

Both real bugs found above are fixed and covered by regression tests.
`tests/test_autograd.py`, `tests/test_tokenizer.py`, and
`tests/test_model.py` are all green after the fixes (see `demo.sh` for the
full run).
