# Glean

A full-text search engine built from scratch in pure Python 3 (stdlib
only): a hand-written Porter stemmer, a positional inverted index with a
real on-disk binary format, a boolean/phrase/proximity query language,
Okapi BM25 ranking with highlighted snippets, typo-tolerant fuzzy search,
prefix autocomplete, and an interactive server-backed browser search UI.

## What it is

Every real search engine — Lucene, Elasticsearch, the original Google —
rests on the same core idea: instead of scanning every document for every
query, invert the relationship and map each *term* to the documents (and
positions) it occurs in. Glean builds that whole stack from first
principles:

- **Analyzer** — a Unicode-aware tokenizer plus a from-scratch
  implementation of the Porter (1980) stemming algorithm (the real
  consonant/vowel "measure" and suffix-stripping rules, verified against
  the exact examples in Porter's own paper — not a stub).
- **Index** — a positional inverted index (`term -> {doc_id: [positions]}`)
  with a genuine on-disk binary format: the source of truth on disk is the
  per-document token stream, and `load()` rebuilds postings, document
  lengths, and averages from it — a real reconstruction, not a pickle dump.
- **Query engine** — a small query language (`word`, `"exact phrase"`,
  `AND`/`OR`/`NOT`, parenthesized grouping, `word1 NEAR/3 word2`
  proximity) compiled to postings-list set algebra and positional
  intersection.
- **Ranking** — Okapi BM25 (with a TF-IDF cosine scorer included for
  comparison) producing ranked results with highlighted, extracted
  snippets.
- **Fuzzy search** — a hand-written Levenshtein DP plus a BK-tree index
  over the vocabulary, powering "did you mean" suggestions for misspelled
  queries.
- **Autocomplete** — a prefix trie over real (unstemmed) corpus words,
  ranked by frequency.
- **Browser UI** — a single-page, server-backed search interface (all
  parsing/ranking logic stays in Python; the browser only renders) with
  live search-as-you-type, autocomplete, and "did you mean" suggestions.

## How to run it

```
# from inside this directory
python3 -m glean.cli demo-index -o glean.idx      # index the bundled 50-article demo corpus
python3 -m glean.cli search "roman empire" -i glean.idx
python3 -m glean.cli stats -i glean.idx

python3 -m glean.cli serve --demo -i glean.idx     # interactive UI at http://127.0.0.1:8752/
```

Index your own text instead of the demo corpus:

```
python3 -m glean.cli index /path/to/txt-or-md-files -o mine.idx
python3 -m glean.cli search "your query" -i mine.idx
```

Query syntax: bare words default to OR (`roman empire` matches either),
`AND`/`OR`/`NOT` connectives, `"exact phrase"` matching, parenthesized
grouping (`cooking AND (pasta OR bread)`), and `word1 NEAR/3 word2`
proximity search. A hyphenated or apostrophe'd query word (`well-known`,
`don't`) is automatically treated as an implicit phrase, matching how it
was actually tokenized at index time.

Run the whole verification suite (unit tests, CLI walkthrough, persistence
round trip, live JSON API, headless-browser UI smoke test) with:

```
./demo.sh
```

## Full feature list

**Required:**
1. Analyzer pipeline (Unicode tokenizer + from-scratch Porter stemmer,
   verified against the algorithm's own paper).
2. Positional inverted index with incremental `add_document` and a real
   binary on-disk format (`glean/index.py`).
3. Boolean + phrase + proximity query engine, verified against a
   brute-force oracle (300-query randomized fuzz test plus a curated
   battery — `glean/query.py`).
4. Okapi BM25 ranking with highlighted, extracted snippets
   (`glean/rank.py`).

**Stretch (all shipped):**
5. Fuzzy / typo-tolerant search — Levenshtein edit distance + a BK-tree,
   with "did you mean" suggestions on the CLI and in the browser UI
   (`glean/fuzzy.py`).
6. Prefix autocomplete — a frequency-ranked trie over real corpus words
   (`glean/trie.py`).
7. Interactive server-backed search UI — `glean/server.py` +
   `static/index.html`, dark/light aware, live search-as-you-type.

## Why this today

Every prior daily build in this repo has picked a systems or graphics
topic — renderers, VCS, databases, compilers, crypto. Information
retrieval is a different kind of interesting: the "obvious" implementation
(grep every document) is asymptotically wrong, and the fix requires real
algorithmic machinery (positional indexes for phrase queries, BM25's
document-length normalization, edit-distance metric trees for fuzzy
matching) that's independently checkable against brute-force oracles at
every layer. It's also genuinely useful — point it at a folder of your own
notes and it works.

## Verification

- 111 Python unit/differential/property tests (`tests/`), including a
  300-query randomized fuzz test that builds random AND/OR/NOT/NEAR/paren/
  phrase query trees and checks every one against a brute-force scan of
  each document's raw token stream — independent of the postings-based
  execution path.
- `demo.sh` — 22 end-to-end checks: the full test suite, a CLI walkthrough
  of every query-language feature (including a "did you mean" check and a
  malformed-query error-message check), an index save/load/re-query
  round trip, live JSON API checks against a real running server (search,
  autocomplete, stats, 400 on bad syntax, 404 on unknown routes), and a
  headless-Chromium walkthrough of the actual browser UI (typing,
  highlighting, autocomplete, tab-complete, clicking a "did you mean"
  suggestion, and error display).
- `REVIEW.md` documents the Phase 3 adversarial review: 7 real bugs found
  and fixed, including two correctness bugs a user would hit constantly
  (unsearchable titles, `NOT` silently behaving like `OR`) and a crash
  (stemmer `RecursionError` on pathological input).

## Where a human could take this next

- **Persist the fuzzy/autocomplete structures.** They're currently rebuilt
  in memory from the loaded index's document text on first use; for a
  large corpus, persisting the BK-tree and trie alongside the index file
  would avoid that rebuild cost on every `serve` startup.
- **Relevance feedback / field boosting.** Titles are folded into the same
  token stream as the body today (a deliberate simplicity trade-off); a
  natural next step is field-weighted scoring (title matches worth more
  than body matches) the way real engines do.
- **Multi-word fuzzy matching and query expansion.** Fuzzy matching
  currently only kicks in for terms that already have zero results;
  extending it to proactively expand every query term (with a rank
  penalty for fuzzy matches vs. exact ones) would smooth over typos in
  the middle of an otherwise-successful query.
- **Concurrent/streaming indexing.** `add_document` is synchronous and the
  binary format is a monolithic file; a real deployment would want
  incremental segment files merged in the background (essentially the
  LSM-tree architecture from this repo's earlier `Strata` build) instead
  of rewriting the whole index on every save.
- **A ranking explain mode.** BM25's per-term contributions are already
  computed internally (`BM25.score`); exposing them per result (why did
  this document rank here?) would make the engine much easier to tune.
