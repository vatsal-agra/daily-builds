# Adversarial Review — Sift

Phase 3: attacking the Phase-2 build as a hostile reviewer. Each issue below
was reproduced before being fixed, and each fix has a regression test.

## Issues found and fixed

### 1. CRITICAL — unclosed phrase quote silently corrupts the query instead of erroring
`sift search '"unclosed phrase'` (a typo missing the closing quote) did not
raise an error. The query tokenizer's `"[^"]*"` alternative only matches a
*balanced* quoted run, so an unterminated `"` falls through to the plain-word
alternative and gets tokenized as `"unclosed` (leading quote, no trailing
one) followed by `phrase`. The old `_build_phrase_leaf` blindly did
`tok[1:-1]`, assuming the first and last characters were the opening and
closing quotes — for `"unclosed` that strips the real trailing letter `d`
too, silently turning the query into a phrase search for `unclose` with no
error at all. A user would get confusing zero/wrong results with no
indication they mistyped the query.
**Fix:** `sift/query.py` now only treats a token as a phrase if it both
starts and ends with `"` and is at least 2 characters long; otherwise it
raises `QueryError("unterminated phrase — missing closing quote")`.

### 2. MODERATE — `*` anywhere but the end of a wildcard term is silently swallowed as a dead literal term
`abc*def` (asterisk in the middle — a plausible typo for `abc*` or `*def`)
didn't raise an error or expand as a wildcard. `_build_word_leaf` only
special-cased tokens *ending* in `*`; anything else fell through to
`TermLeaf(analyze_query_term(tok))`, stemming the literal string
`"abc*def"` into a garbage term that can never appear in any real index
(index terms never contain `*`), so the query always silently returns zero
results with no explanation.
**Fix:** any token containing `*` is now validated: exactly one `*`, at the
end, with a non-empty prefix — otherwise `QueryError` explains the rule.

### 3. MODERATE — "did you mean" suggestions are polluted by boolean-operator keywords
`sift search "quantumm AND nonexistentxyz"` (a real typo, `quantumm` for
`quantum`) printed `did you mean: ad, add, end, hand, land?` — completely
useless, because the suggestion code iterated over every whitespace-split
word in the raw query *including* the literal operator keywords `AND`/`OR`/
`NOT`, ran a BK-tree fuzzy lookup on `"and"` itself, and let its nearest
vocabulary neighbors crowd out the one suggestion that actually mattered
(`quantum`). Reproduced in both the CLI (`sift/cli.py`) and the HTTP API
(`sift/server.py`), which share the same logic.
**Fix:** both now skip tokens that case-insensitively equal `and`/`or`/`not`
before computing suggestions.

### 4. MINOR — a source document whose first line is blank gets an empty title
`build_index_from_dir` picked `text.splitlines()[0]` as the title, guarded
only by "is the *whole* document non-empty" — a document starting with a
blank line (before its actual title line) would get `""` as its displayed
title, which is confusing in search results and in the HTML UI.
**Fix:** `sift/index.py` now scans forward for the first non-blank line and
falls back to the filename only if the entire document is blank.

## Investigated, not a bug — documented behavior

- **Empty parentheses `()`** raise `QueryError("missing closing parenthesis")`
  rather than a more precisely-worded "empty group" message. The query is
  still rejected cleanly with no crash and no silent misbehavior, so this is
  a cosmetic wording gap, not a correctness issue — left as is.
- **Phrase queries containing a stopword survive only if the stopword's
  position gap is reproduced exactly** (e.g. `"day and night"` requires
  "day" and "night" exactly two raw token positions apart in the source
  text, matching the phrase's own internal gap). A phrase made entirely of
  stopwords (e.g. `"the a"`) can never match anything, since none of its
  words are indexed. This is a deliberate, documented trade-off from
  PLAN.md (indexing skips stopwords to keep the index smaller), not a bug —
  confirmed by `tests/test_query.py::TestPhraseQueries`.
- **`snippet_for()` re-reads the original source file from `doc.path` at
  query time** rather than storing raw text in the on-disk index. This
  means a `.sift` index file is only useful for snippets if the original
  corpus directory is still present at the same path — a real constraint,
  but an intentional one (storing full source text in the index would
  bloat the "mini Lucene segment" format this build is demonstrating, and
  real search engines separate stored fields from the index for the same
  reason). Documented in `sift/storage.py`'s module docstring.

## Fixed but worth calling out: test-suite bugs found while writing tests

Two of the four issues surfaced through direct hostile testing of the CLI
(section above). Three *additional* problems were self-inflicted mistakes
in the test suite itself, caught the moment the suite ran red — logged here
because "the test was wrong" is itself a finding worth being honest about:

- `test_phrase_agrees_with_naive_oracle_no_internal_stopwords` originally
  built its oracle by stripping stopwords out of the document before
  checking contiguity, which silently changes phrase semantics (it would
  call `"fox dog"` a match against `"fox and the dog"` in the source text,
  which the real engine correctly rejects because there are words between
  them). Fixed the oracle to scan the *unfiltered* token stream instead.
- `test_topical_query_surfaces_right_topic` and `test_boolean_not_excludes_docs`
  both assumed words (`"programming"`, `"language"`, `"space"`) were present
  in specific corpus documents without checking — the Python article never
  actually uses the word "programming", and the Mars-rovers article never
  uses the word "space". Fixed by picking query terms actually present in
  the target documents (verified via `idx.doc_freq(...)` before adjusting
  the test).

## Fixed

All four real issues above are fixed in `sift/query.py`, `sift/cli.py`,
`sift/server.py`, and `sift/index.py`, each with a new regression test in
`tests/test_query.py` / `tests/test_engine_cli.py` / `tests/test_index.py`.
Full suite green after fixes — see the final test run count in README.md.
