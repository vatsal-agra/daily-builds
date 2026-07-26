# Sift — a full-text search engine, built from scratch

## Concept

Every previous "from scratch" build in this ledger that touches information
retrieval went the *vector* route (VecNN: HNSW/LSH over embeddings). Nobody
has built the other half of the field yet: classic **lexical full-text
search** — the inverted-index, BM25, boolean/phrase-query machinery that
still powers Lucene/Elasticsearch/Postgres FTS/every code search bar you've
ever used. That's today's build: **Sift**, a search engine from raw text to
ranked, snippeted, typo-tolerant results, with no search library anywhere in
the dependency graph.

## Why this is interesting

- It's a real, still-load-bearing piece of infrastructure most engineers use
  daily but few have built. The gap between "grep" and "a search engine" is
  entirely inverted indexes, ranking math, and query semantics — all of it
  representable in a few hundred lines of clear, testable code.
- Every core piece has a mathematically checkable ground truth: BM25 scores
  can be verified against a brute-force reference implementation; phrase
  queries can be verified against literal substring scans; edit-distance
  fuzzy matching can be verified against a naive O(nm) Levenshtein oracle.
  That means Phase 5 isn't just "it runs" — it's "it's provably correct
  against an independent, dumber implementation."
- It composes naturally into a real, usable product: index a folder of
  documents, get a ranked search box with highlighted snippets and
  "did you mean" suggestions, in the browser.

## Architecture

```
text corpus (.txt/.md files)
        │
        ▼
  ┌─────────────┐   lowercase, unicode-aware tokenize, stopword filter,
  │  Analyzer   │   Porter-stemmer (real algorithm, from scratch)
  └─────────────┘
        │ token stream (with positions)
        ▼
  ┌─────────────┐   term → postings list: [(doc_id, term_freq, [positions])]
  │  Indexer    │   + per-doc length, doc count, avg doc length
  └─────────────┘   + a term trie (prefix/wildcard) + a BK-tree (fuzzy)
        │
        ▼  serialize to a custom binary segment format (varint delta-coded
  ┌─────────────┐   postings, like a mini Lucene segment) on disk
  │   Index     │
  │  (on disk)  │◄──── load back for querying without re-indexing
  └─────────────┘
        │
        ▼
  ┌─────────────┐  parse query → AND/OR/NOT boolean tree, "phrase" via
  │Query Engine │  position-adjacency intersection, term* via trie prefix
  └─────────────┘  scan, fuzzy~ via BK-tree edit-distance radius search
        │
        ▼
  ┌─────────────┐  BM25(k1, b) per matching doc, summed across query terms
  │   Ranker    │  → sorted results
  └─────────────┘
        │
        ▼
  ┌─────────────┐  best-window snippet extraction + <mark> highlighting
  │  Presenter  │  + spelling suggestions when zero results
  └─────────────┘
        │
        ▼
   CLI  +  stdlib http.server backend  +  single-file HTML search UI
```

## Feature list

### Required (core, must fully work end-to-end)

1. **Analyzer + inverted index construction** — tokenizer (unicode word
   boundaries, case folding), stopword filtering, a real from-scratch Porter
   stemmer (not a stub — the actual multi-step suffix-stripping algorithm),
   and an inverted index mapping term → postings (doc id, term frequency,
   token positions), plus per-document length and corpus statistics needed
   for ranking.
2. **Boolean + phrase query engine** — parse queries with `AND`/`OR`/`NOT`,
   parenthesized grouping, and `"quoted phrase"` queries resolved via
   position-adjacency checks against the postings lists (not substring
   search — real positional intersection).
3. **BM25 ranking** — Okapi BM25 with configurable `k1`/`b`, correct IDF
   (with negative-IDF floor handling), correct document-length
   normalization, verified term-by-term against a brute-force reference
   scorer that recomputes everything from the raw corpus.
4. **Fuzzy / typo-tolerant matching** — a BK-tree built over the index
   vocabulary supporting real Levenshtein-distance range queries, powering
   both `term~` fuzzy query syntax and "did you mean" suggestions when a
   query returns zero results, verified against a naive O(n·m)
   edit-distance oracle.

### Stretch (2+)

5. **Wildcard / prefix search** — a term trie supporting `prefix*` queries
   that expand to the union of postings for every matching term.
6. **Snippet generation + highlighting** — best-matching-window extraction
   per result (densest cluster of query-term hits) with `<mark>`-tagged
   highlighting, shown in both the CLI and the web UI.
7. **On-disk binary segment format** — a real persisted index (magic
   header, varint delta-encoded postings, offset table) so `sift search`
   works instantly against a prebuilt index without re-tokenizing the
   corpus, with a round-trip-verified loader.
8. **Interactive HTML search UI** — a small `http.server`-backed API plus a
   single self-contained HTML/CSS/JS front end: a real search box hitting
   the real Python ranking engine (no mocked JSON), with snippets,
   highlighting, result timing, and "did you mean" suggestions.

## Test corpus

Since the whole point is to demonstrate correct, meaningful ranking, Sift
ships with a self-authored synthetic corpus of ~40 short documents across
distinct topics (space exploration, cooking, classical history, programming
languages, sports, music theory, ...) written specifically for this build —
original text, not scraped, so there are no licensing/accuracy concerns and
topic clustering is known ahead of time for verifying ranking makes sense.

## Plan for verification

- Brute-force BM25 oracle (recompute term frequencies and document
  frequencies directly from the raw corpus, independent of the index data
  structures) checked against the indexed/optimized path.
- Naive substring-based phrase-match oracle checked against the positional
  intersection path.
- Naive O(n·m) Levenshtein oracle checked against BK-tree fuzzy results.
- Round-trip test: build index → serialize to disk → reload → identical
  query results before and after.
