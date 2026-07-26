# Glean

*Status: Phase 2 — core build complete. All 4 required features working end-to-end.*

A from-scratch full-text search engine — real tokenization, Porter stemming, a
persistent inverted index, boolean/phrase queries, BM25 ranking, and typo-tolerant
fuzzy matching — with zero search-library dependencies (pure Python 3 stdlib).

Its flagship demo indexes this very repository's history: every prior daily build's
`README.md`/`PLAN.md`/`REVIEW.md` plus the root `LEDGER.md` becomes searchable.

See [PLAN.md](./PLAN.md) for the full concept, architecture, and feature list.

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
python3 -m glean.cli demo
```

## Query syntax

- Bare words: `raft consensus` — ranked OR (any doc containing either term scores;
  docs containing both score higher).
- `AND` / `NOT`: `chess AND transposition`, `raft NOT chess` — hard filters.
- `"quoted phrase"`: requires the exact phrase (word order + adjacency), not just
  co-occurrence.
- Misspelled terms are automatically corrected via Levenshtein/BK-tree fuzzy lookup
  when there's no exact match, with the correction shown in results.

## Status

This README is updated after every build phase. Remaining work: adversarial review
(Phase 3), stretch features + polish (Phase 4), a full test suite + demo script
(Phase 5), and final packaging (Phase 6).
