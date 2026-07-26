# Glean

A from-scratch full-text search engine — real tokenization, a from-scratch Porter
stemmer, a persistent inverted index with delta-compressed varint postings, boolean
(`AND`/`OR`/`NOT`) and exact-phrase queries, BM25 relevance ranking, and typo-tolerant
fuzzy matching via a BK-tree — with zero search-library dependencies (pure Python 3
stdlib, no `whoosh`, no `sqlite` FTS, no `nltk`).

Its flagship demo indexes this very repository's own history: every prior daily
build's `README.md`/`PLAN.md`/`REVIEW.md`, plus the root `LEDGER.md`, becomes
instantly searchable — "which of these 35+ projects touched Raft? Which one used a
Bloom filter? Did I already build something like this?" now has a real answer.

## Why this, today

Prior builds in this repo covered *vector* search (HNSW/LSH in VecNN) and
*structured* query (PicoSQL's SQL engine), but never classic lexical information
retrieval — the field behind Elasticsearch/Lucene/Sphinx. It has its own real
engineering subtlety (position-aware phrase adjacency, TF saturation, document-length
normalization, edit-distance fuzzy lookup) and, unusually for a from-scratch demo, is
immediately useful on day one against a corpus that already existed: this repo.

## Quick start

```bash
cd 2026-07-26-glean

# Index any directory of .md/.txt files (writes a .glean/ index dir alongside it)
python3 -m glean.cli index /path/to/some/docs

# Search it from the terminal
python3 -m glean.cli search "bloom filter" --dir /path/to/some/docs
python3 -m glean.cli search '"exact phrase"' --dir /path/to/some/docs
python3 -m glean.cli search "chess AND transposition" --dir /path/to/some/docs
python3 -m glean.cli search "raft NOT chess" --dir /path/to/some/docs

# Or launch the web search UI
python3 -m glean.cli serve --dir /path/to/some/docs --port 8899
# -> http://127.0.0.1:8899/

# See index stats
python3 -m glean.cli stats --dir /path/to/some/docs

# Self-indexing demo: indexes this whole daily-builds repo and runs sample queries
# (writes its index to ./.demo_index inside this project folder, never touches
# anything outside it)
python3 -m glean.cli demo
```

## Query syntax

- Bare words: `raft consensus` — ranked OR (any doc containing either term scores;
  docs containing more of them score higher via summed BM25).
- `AND` / `NOT`: `chess AND transposition`, `raft NOT chess` — hard filters (both
  sides of an `AND` are required; a query made entirely of `NOT` clauses searches
  the whole corpus minus the exclusion).
- `"quoted phrase"`: requires the exact phrase — word order and adjacency, not just
  co-occurrence — and is never altered by fuzzy correction (an exact phrase means
  exactly what you typed).
- Misspelled bare terms are automatically corrected via Levenshtein/BK-tree fuzzy
  lookup when there's no exact match, with the correction shown in results
  (`--no-fuzzy` to disable).

## Architecture

`crawler` walks a directory (skipping `.git`/`.glean`/`node_modules`/hidden dirs) →
`analyzer` tokenizes, folds case, strips stopwords, and stems with a from-scratch
Porter (1980) implementation validated against Martin Porter's own 75-word published
test vocabulary → `index` builds a two-stage inverted index (a cached per-document
forward index for mtime-based incremental reindexing, inverted into a term
dictionary + a binary postings file using delta-compressed varints, the same shape
real search engines use on disk) → `query` parses boolean/phrase syntax and ranks
matches with BM25 (k1=1.5, b=0.75), falling back to BK-tree fuzzy lookup for
unmatched terms → `cli`/`server` expose it all over a terminal and a
single-page web UI with highlighted snippets.

## Web UI

`glean serve` hosts a single-page, no-framework search UI (dark/light mode aware)
with ranked results, highlighted snippets (Markdown syntax noise like `#`/`**`/
backticks is stripped for readability without touching real content like
`__init__.py`), a live document/term count, and clickable "did you mean" fuzzy
suggestions when a query has zero results.

## Testing

```bash
python3 -m unittest discover -s tests   # 81 tests: analyzer, index, query, fuzzy, crawler, snippet, CLI
./demo.sh                                # tests + CLI walkthrough + HTTP API smoke test + self-index demo
```

## Feature list

**Required (all 4 shipped):**
1. Analyzer pipeline (tokenizer, case folding, stopwords, from-scratch Porter stemmer)
2. Persistent, incrementally-updated inverted index with binary varint postings
3. Boolean (`AND`/`OR`/`NOT`) + exact-phrase query engine with BM25 ranking
4. CLI (`index`/`search`/`stats`/`serve`/`demo`) + a real web search UI

**Stretch (both shipped):**
5. Typo-tolerant fuzzy matching (Levenshtein + BK-tree, with "did you mean")
6. Self-indexing demo over this repo's own multi-month build history

See [PLAN.md](./PLAN.md) for the original concept and [REVIEW.md](./REVIEW.md) for
the adversarial-review and verification bug hunt (6 real issues found and fixed
across both passes, including a boolean-logic bug the adversarial review missed
that the test suite caught).

## Where a human could take this next

- **Ranking quality**: add field boosting (title matches > body matches), or a
  learned re-ranker over BM25's top-K.
- **Query language**: wildcard/prefix queries (`raft*`), range queries on
  frontmatter/metadata, nested boolean groups with parentheses.
- **Scale**: the whole index currently loads into memory per process; a real
  multi-gigabyte corpus would want on-disk skip lists / block-compressed postings
  and a merge-based segment architecture instead of full rebuild-on-write.
- **Snippets**: multiple non-overlapping match windows per document instead of just
  the first match; sentence-boundary-aware trimming instead of nearest-whitespace.
- **Corpora beyond Markdown**: PDF/HTML/code-aware tokenization (e.g. treating
  `snake_case`/`camelCase` identifiers as compound terms) so `glean index` works
  well over a real codebase, not just prose docs.
