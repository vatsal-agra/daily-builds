# Adversarial review

Hostile review of Trove's Phase 2 core build, done by deliberately trying
to break the query parser, the indexer, and the CLI with malformed,
adversarial, and boundary inputs. Each finding was reproduced first, then
fixed; the fixes are described alongside each item.

## Findings

### 1. Duplicate `doc_id` crashes the indexer (correctness / robustness)

`InvertedIndex.add_document` correctly rejects a duplicate `doc_id` by
raising `ValueError` — but neither `build_index` (generic recursive
indexer) nor `build_repo_history_index` (this repo's own LEDGER.md
splitter) guaranteed uniqueness before calling it. Two `## ` sections in
the same markdown file sharing an identical header title, or two
LEDGER.md entries with an identical title string, would crash `trove
build` outright.

This isn't hypothetical for *this* repository specifically: its own
history already contains multiple same-named projects shipped on
different days by parallel sessions (three "Strata"s, several
"Resolvent"s, two "Gambit"s, two "Lumina"s) that only avoided an exact
collision by luck of slightly different dates/suffixes in the title
string. A future identically-titled duplicate is a realistic event, not
a contrived edge case.

**Fix:** added `_unique_doc_id()` in `index.py`, used by both
`build_index` and `build_repo_history_index`, which appends `" (2)"`,
`" (3)"`, ... on collision instead of crashing.

### 2. Unterminated phrase silently changes query meaning (UX)

A query like `"unclosed phrase` (missing the closing quote) doesn't
raise an error — the lexer's `PHRASE` pattern simply fails to match, the
lone `"` is dropped as junk, and `unclosed` and `phrase` are silently
re-parsed as two ordinary implicit-AND words. The user gets a result set
for a completely different query than the one they typed, with no
warning.

**Fix:** `parse_query()` now checks for an odd number of `"` characters
up front and raises `QuerySyntaxError("unterminated phrase — missing a
closing '\"'")` before lexing.

### 3. `-(...)` and `-"..."` silently drop the negation (correctness)

The negation shortcut (`-word`) only triggered when `-` was lexically
fused to a bare word token. `-(fox AND lazy)` and `-"exact phrase"` both
have `-` fused to a non-word character, which the old `WORD` regex
couldn't match at all — the stray `-` was dropped as junk and the
*positive* (non-negated) group/phrase was evaluated instead. Verified by
reproduction: `-(fox AND lazy)` against a fixture where `fox AND lazy`
matches exactly one doc returned that same doc instead of everything
except it — the exact opposite of what the query asked for. This is a
silent-wrong-answer bug, worse than a crash.

**Fix:** the lexer now emits a dedicated token for `-` immediately
followed by `(` or `"` (no whitespace), and the parser's `NotExpr` rule
consumes it the same way it already consumed `-word`.

### 4. No bound on query length or recursion depth (robustness / DoS)

`Engine.search` fed arbitrary user input straight into the
recursive-descent parser with no length cap. A pathological query of a
few thousand `(` characters (trivial to construct, e.g. from a
malicious HTTP request once the server ships in Phase 4) would recurse
deep enough to raise `RecursionError`, which `Engine.search` didn't
catch — an unhandled exception would crash a request handler.

**Fix:** `Engine.search` now truncates queries to 300 characters (ample
for any real query; the longest realistic phrase/boolean query in this
project's own tests is well under 100) and explicitly catches
`RecursionError` alongside `QuerySyntaxError`, returning the same
friendly `error` field either way instead of propagating.

### 5. Negative `--top` silently returns the wrong slice (correctness)

`ranking.rank()` sliced with `ordered[:top]`. Python's negative-index
slicing semantics mean `--top -1` doesn't mean "no limit" or raise an
error — it silently returns *all but the last* result, an answer that
looks plausible but is simply wrong for what the user asked. `--top 0`
degrades "gracefully" to zero results, which is at least not misleading,
but the negative case is a real trap.

**Fix:** `Engine.search` now clamps `top = max(0, top)` before it's used
anywhere.

### 6. Fixed fuzzy-correction distance produces nonsense on short words (quality)

The BK-tree fuzzy corrector used a single fixed edit-distance threshold
(2) regardless of query-term length. For a short term this is far too
permissive: at distance 2, a 3-letter typo can "correct" to almost any
other 3-5 letter vocabulary word, silently substituting a term the user
never typed and didn't mean. This is the same problem real search
engines hit and the same fix they use.

**Fix:** added `fuzzy.auto_fuzzy_distance()`, an Elasticsearch-style
length-scaled threshold (distance 0 for terms ≤3 chars — i.e. no fuzzy
correction at all for very short words — 1 for 4-5 chars, 2 for longer),
used by default; an explicit numeric override is still accepted for
callers (tests, advanced CLI use) that want to force a specific
distance.

### 7. `--ext` is case-sensitive against a case-normalized file scan (bug)

`iter_corpus_files` matches extensions via `name.lower().endswith(extensions)`
— it lowercases the filename but never lowercased the user-supplied
`--ext` tuple. `trove build . --ext TXT` therefore matched *zero* files
silently misreported as "no files found" instead of working the same as
`--ext txt`. Reproduced directly.

**Fix:** `_cmd_build` now lowercases and strips each extension before
building the tuple, and drops empty entries from a stray trailing comma.

### 8. Dead code / repeated work in the stemmer (cleanliness)

`_step4` re-sorted its 18-entry suffix list by length on *every single
call* — across a ~1200-word README that's over a thousand redundant
sorts for a constant result. It also contained an unreachable
`if suffix == "ion": continue` guard for a string that was never in the
list it was iterating (the real `(s|t)ion` rule is handled separately,
earlier in the function, and correctly so — this line did nothing).

**Fix:** hoisted the sorted suffix list to a module-level constant
(`_STEP4_SUFFIXES_BY_LEN`), removed the dead branch.

## Not fixed — considered and accepted

- **BM25 `k1`/`b` are unclamped.** These are deliberately exposed tuning
  knobs (`--k1`, `--b` on `trove search`), the same way a real search
  engine lets you experiment with relevance tuning. Clamping them to
  "sane" ranges would fight the point of exposing them.
- **Prefix (`term*`) queries scan the full vocabulary linearly.** Fine
  at this corpus's scale (~4,000 terms, sub-millisecond). Phase 4's
  autocomplete trie is a natural place to also accelerate this, and it
  is used for exactly that.
- **A single stray `-` (surrounded by whitespace, not fused to a word,
  phrase, or paren) is silently dropped rather than erroring.** Treating
  every bare `-` as a syntax error would be hostile to users who type a
  literal hyphen; silently ignoring an unfused one is the same choice
  most search UIs make.
- **XSS-safe escaping of corpus-derived text in the web UI.** Several
  past projects' READMEs contain literal `<script>`/HTML-like text in
  code examples, so this is a real, not hypothetical, risk once search
  results are rendered in a browser (Phase 4). Addressed directly during
  the server/UI implementation (proper HTML-escaping at render time)
  rather than as a Phase 3 patch to code that doesn't exist yet — see
  Phase 4 write-up in the README for how it was verified.

## Gate check

All eight fixed findings above were re-run after the fix and now behave
correctly; see `tests/test_query.py`, `tests/test_index.py`,
`tests/test_fuzzy.py`, `tests/test_cli.py` and `tests/test_engine.py`
for the regression tests added for each one (Phase 5 runs the full
suite green).
