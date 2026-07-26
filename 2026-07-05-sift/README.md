# Sift

A full-text search engine built entirely from scratch in Python — the
inverted-index/BM25/boolean-query machinery behind Lucene, Elasticsearch,
and Postgres full-text search, with no search library anywhere in the
dependency graph. Tokenizer, a real from-scratch Porter stemmer, an
inverted index, a boolean/phrase/wildcard/fuzzy query engine, BM25 ranking,
a BK-tree for typo tolerance, a custom on-disk binary index format, and an
interactive HTML search UI.

## Why this, today

Every previous "from scratch" search-adjacent build in this repo's history
(VecNN, 2026-06-27) went the *vector* route — embeddings, HNSW, LSH.
Nobody had built the other half of information retrieval yet: classic
lexical full-text search. The gap between `grep` and a real search engine
is entirely inverted indexes, ranking math, and query semantics — all of it
representable in a few hundred lines of code, and every core piece has a
mathematically checkable ground truth (BM25 scores can be verified against
a brute-force reference implementation; phrase queries against literal
positional scans; fuzzy matching against a naive edit-distance oracle).
That combination — genuinely useful, algorithmically rich, and rigorously
verifiable — is exactly what this daily-build format rewards.

## How to run it

```bash
cd 2026-07-05-sift

# the 40-document test corpus is already committed under corpus/, but is
# fully reproducible:
python3 corpus/generate_corpus.py

# build an index, then query it
python3 -m sift.cli index corpus -o demo.sift
python3 -m sift.cli search "mars rover" -i demo.sift
python3 -m sift.cli search '"black hole"' -i demo.sift --no-snippets
python3 -m sift.cli search "space AND NOT mars" -i demo.sift
python3 -m sift.cli search "quan*" -i demo.sift            # wildcard
python3 -m sift.cli search "pytho~2" -i demo.sift           # fuzzy
python3 -m sift.cli search "quantumm" -i demo.sift          # typo -> "did you mean: quantum?"

# interactive HTML UI backed by the real Python ranking engine
python3 -m sift.cli serve -i demo.sift
# -> open http://127.0.0.1:8000

# canned tour of every feature in one command
python3 -m sift.cli demo
```

Run the tests:

```bash
python3 -m unittest discover -s tests   # 123 unit tests
./demo.sh                               # 30-check end-to-end walkthrough (CLI + live HTTP server)
```

## Feature list

**Required (core):**
1. **Analyzer + inverted index** — unicode-aware tokenizer, stopword
   filtering, and a real from-scratch Porter stemmer (all five suffix-
   stripping steps, verified against Porter's own reference vocabulary),
   building a term → (doc id, term frequency, positions) postings index.
2. **Boolean + phrase query engine** — `AND`/`OR`/`NOT` with parenthesized
   grouping, and `"exact phrase"` queries resolved by true positional
   adjacency in the postings lists (not substring matching).
3. **BM25 ranking** — Okapi BM25 with configurable `k1`/`b`, verified
   term-by-term against an independent brute-force scorer that
   re-tokenizes the raw corpus from scratch.
4. **Fuzzy / typo-tolerant matching** — a BK-tree over the index vocabulary
   with real Levenshtein-distance range queries, powering `term~N` fuzzy
   search and "did you mean" suggestions, verified against a naive O(n·m)
   edit-distance oracle.

**Stretch:**
5. **Wildcard / prefix search** — a trie supporting `prefix*` queries.
6. **Snippet generation + highlighting** — best-matching-window extraction
   (densest cluster of query-term hits) with `<mark>`-tagged highlighting.
7. **On-disk binary index format** — a real persisted "mini Lucene segment"
   (varint delta-encoded postings, magic header) so `sift search` works
   instantly against a prebuilt index without re-tokenizing the corpus.
8. **Interactive HTML search UI** — a small `http.server` JSON API plus a
   self-contained, dark-mode-aware HTML/CSS/JS front end (no build step, no
   CDN) hitting the real ranking engine — verified in a real headless
   Chromium browser, light and dark, with results/no-results states.

## Verification

- `tests/test_stemmer.py` — Porter stemmer checked against 75 of Porter's
  own reference vocabulary pairs, plus the exact worked examples from his
  1980 paper for the `measure()` helper.
- `tests/test_rank.py` — every indexed BM25 score cross-checked against an
  independent brute-force recomputation from raw text, across many queries,
  documents, and 30 random term subsets (all exact to 9 decimal places).
- `tests/test_fuzzy.py` — BK-tree range queries checked against a naive
  Levenshtein scan across hand-picked and randomly generated vocabularies
  and radii.
- `tests/test_query.py` — boolean precedence, phrase adjacency (including
  a from-scratch positional oracle), wildcard/fuzzy expansion, and parser
  error handling.
- `tests/test_storage.py` — the on-disk binary format round-trips
  vocabulary, postings, and query results exactly.
- `tests/test_engine_cli.py` — the real CLI run as a subprocess against the
  real 40-document corpus.
- `demo.sh` — 30 checks driving the actual CLI and a live HTTP server
  (`curl` against real endpoints), not mocks.
- `REVIEW.md` — the Phase 3 adversarial review: 4 real bugs found (an
  unterminated phrase quote silently corrupting the query instead of
  erroring; a misplaced wildcard `*` silently searching a dead literal term;
  boolean-operator keywords polluting "did you mean" suggestions; a blank
  leading line producing an empty document title) and fixed with regression
  tests.

## Where a human could take this next

- **Relevance feedback**: track which results get clicked and blend that
  signal into ranking (a tiny, from-scratch learning-to-rank layer).
- **Faceted search**: tag documents with metadata (category, date, author)
  and support `category:physics AND black hole`-style filtered queries.
- **Incremental indexing**: right now `sift index` always rebuilds from
  scratch; a real system would support adding/updating/deleting individual
  documents without a full re-tokenize, likely via a small write-ahead
  segment + periodic merge (much like the LSM-tree KV store shipped
  2026-06-28 in this same repo).
- **Multi-field documents**: separate title/body/tags fields with
  per-field boosting (a title match should usually outrank a body match).
- **Stemming alternatives**: swap in a lemmatizer or a language-specific
  stemmer and compare ranking quality — the analyzer is a clean seam for
  this (`sift/analyzer.py` + `sift/stemmer.py`).
- **Distributed sharding**: partition the corpus across multiple index
  shards and merge ranked results, the way real search clusters scale
  beyond one machine's RAM.
