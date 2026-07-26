# Glean — a from-scratch full-text search engine

## Concept

Every one of these daily builds ships a `PLAN.md`, `README.md`, and often a `REVIEW.md`
buried in its own dated folder. There is no way to ask "which of these projects touched
Raft?" or "did I already build something with a Bloom filter?" without grepping by hand.

Glean is a real full-text search engine — the kind that powers Elasticsearch/Lucene/Sphinx
under the hood, built from first principles with no search library, no `whoosh`, no
`sqlite FTS5` — and its flagship demo corpus is **this repository's own history**: every
`README.md`, `PLAN.md`, `REVIEW.md`, and `LEDGER.md` entry across every `YYYY-MM-DD-*`
folder becomes instantly, richly searchable.

## Why it's interesting

- It's a different corner of "from scratch" than anything shipped so far in this repo:
  prior builds covered *vector* search (HNSW/LSH in VecNN) and *structured* query
  (PicoSQL), but never classic information retrieval — tokenization, stemming, inverted
  indices, and relevance ranking (BM25) are their own deep, well-studied field with
  real engineering subtlety (position-aware phrase queries, term-frequency saturation,
  document-length normalization, fuzzy matching under typos).
- It's immediately, tangibly useful on day one: point it at `daily-builds/` itself and
  you get a working search box over 35+ prior projects' documentation.
- It has a satisfying end-to-end shape: crawl → analyze → index → rank → serve, each
  stage independently testable, each with real failure modes to get right (stemming
  edge cases, BM25 parameter sensitivity, phrase-query position math, edit-distance
  fuzzy matching performance).

## Architecture

```
glean/
  analyzer.py     # tokenizer, lowercasing/unicode-fold, stopword filter, Porter stemmer
  index.py        # inverted index: term -> postings (docID, term freq, positions)
                   # + doc store (length, path, title) + on-disk persistence (JSON+binary postings)
  query.py        # query parser (AND/OR/NOT, "phrase", term*) + BM25 scorer + phrase matcher
  fuzzy.py        # Levenshtein edit distance + BK-tree for typo-tolerant term lookup
  crawler.py      # walks a directory, reads .md/.txt/.py files, mtime-based incremental reindex
  cli.py          # `index`, `search`, `serve`, `stats`, `demo` subcommands
  server.py       # stdlib http.server backend + snippet highlighting (JSON API)
  static/
    index.html    # single-page search UI (no build step, no framework)
tests/
  test_analyzer.py, test_index.py, test_query.py, test_fuzzy.py, test_crawler.py
demo.sh
```

Data flow: `crawler` walks a root directory → yields `(path, text, mtime)` → `analyzer`
tokenizes each document into a stream of (stemmed term, position) pairs → `index` builds
an inverted index (postings lists per term, each posting = docID + positions) plus a doc
store (length in tokens, title, path, mtime) → persisted to `.glean/` as JSON + a compact
binary postings blob → `query` parses a query string into a boolean/phrase AST, resolves
candidate documents via postings intersection/union, scores with BM25 (falling back to
fuzzy BK-tree lookup for terms with zero exact matches), and returns ranked results with
highlighted snippets → `server`/`cli` expose this over a web UI and a terminal.

## Feature list

**Required (4):**
1. **Analyzer pipeline** — Unicode-aware tokenizer, case folding, stopword removal, and a
   real Porter-stemmer implementation (not a stub) so "building"/"built"/"builds" all
   collapse to one indexed term.
2. **Persistent inverted index** — term → postings (doc id, term frequency, ordered token
   positions) built from a crawled corpus, saved to and loaded from disk incrementally
   (mtime-based skip of unchanged files) with zero data loss across restarts.
3. **Boolean + phrase query engine with BM25 ranking** — parses `term1 AND term2`,
   `term1 OR term2`, `NOT term`, `"exact phrase"`, and bare multi-term queries (implicit
   AND-of-should scoring); ranks results with real BM25 (k1/b tunable), using postings
   positions to verify phrase adjacency.
4. **CLI + web search UI** — `glean index <dir>`, `glean search <query>`, and
   `glean serve` (stdlib `http.server`, JSON API) backing a single-page search box with
   ranked results, term-highlighted snippets, and score display.

**Stretch (2+):**
5. **Fuzzy/typo-tolerant matching** — Levenshtein edit-distance search over a BK-tree of
   indexed terms so a misspelled query term (e.g. "Baye" for "bayes", "consesus" for
   "consensus") still surfaces relevant documents, with a "did you mean" suggestion.
6. **Self-indexing demo over this repo's history** — a `glean demo` command that indexes
   `daily-builds/` itself (every prior project's README/PLAN/REVIEW + LEDGER.md) and runs
   a battery of real queries ("raft consensus", "bloom filter", "ray tracing bvh") to
   prove the whole pipeline works end-to-end on real, messy, pre-existing content it
   was never tuned for.

## Non-goals

No external search libraries, no ML embeddings (that's VecNN's territory — this is
classic lexical/statistical IR), no distributed sharding — this is a single-machine,
single-process engine, matching the scope of one day's build.
