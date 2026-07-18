# Trove — a from-scratch full-text search engine

## Concept

Every classical Information Retrieval algorithm that powers Lucene,
Elasticsearch, and web search, implemented from first principles in pure
Python (stdlib only): tokenization → stemming → inverted index → BM25
ranking → a real query language (boolean + phrase + fuzzy) → snippet
generation → autocomplete.

The corpus isn't synthetic filler — it's this repository's own history.
`daily-builds/` now holds 36 past projects, each with a substantial
README (600–1200 words) describing what was built and how. Nobody can
search that archive today except by `grep`, which knows nothing about
relevance, phrases, typos, or ranking. Trove indexes every past README +
the LEDGER.md entries and makes them genuinely searchable: "which project
did conflict-driven clause learning", "CDCL solver -law" (exclude "law"
false-positive), "spreadhseet" (typo, still finds Formulate). It also
works as a general-purpose engine over any directory of text/markdown
files, so it isn't hardcoded to this one corpus — verified in Phase 5
against a second, independent corpus too.

## Why this is interesting

Every other "from-scratch X" build in this repo (SAT solvers, path
tracers, a spreadsheet engine, a SQL engine, a VCS) has picked a single
deep algorithm and built a product around it. Full-text search is a
different flavor: it's a *pipeline* of several distinct, individually
well-known algorithms (edit-distance automata, TF-IDF/BM25 statistics,
trie/BK-tree data structures, boolean query evaluation over postings
lists) that only becomes a real search engine when they're composed
correctly — get the interfaces wrong and you get an engine that's
"basically working" but ranks garbage first or crashes on a typo. That
composition risk is exactly the kind of thing the adversarial-review
phase is built to catch. It also hasn't been done yet in this repo:
VecNN (2026-06-27) did *vector* search (HNSW/LSH over embeddings) — this
is the classical, non-neural counterpart, and the two are complementary,
not overlapping.

## Architecture

```
documents (.md/.txt files)
   │
   ▼
tokenizer.py     lowercase → strip punctuation/markdown syntax → split
                 → stopword filter → Porter stemmer (from scratch)
   │
   ▼
index.py         inverted index: term -> postings list
                 postings = [(doc_id, term_freq, [positions...]), ...]
                 + per-doc length, avg doc length, doc_id -> metadata
                 + JSON persistence (build once, query many times)
   │
   ├─▶ query.py       query language: AND/OR/NOT, parentheses,
   │                  "exact phrase" (positional intersection),
   │                  term* prefix — parsed by a small recursive-descent
   │                  parser into a boolean expression tree, evaluated
   │                  over posting sets
   │
   ├─▶ ranking.py     Okapi BM25 scoring (k1, b tunable) over the
   │                  candidate set the boolean query returns; also a
   │                  raw TF-IDF cosine mode for comparison
   │
   ├─▶ fuzzy.py        BK-tree over the vocabulary (Levenshtein metric,
   │                  from-scratch edit-distance DP) — auto-corrects
   │                  query terms not in the vocabulary to the nearest
   │                  real term(s) before querying
   │
   ├─▶ suggest.py      trie over the vocabulary for prefix autocomplete
   │                  + frequency-ranked suggestions
   │
   └─▶ snippet.py      picks the highest-density window of query terms
                      in each matched document and highlights them —
                      real "context around the match", not just doc title
   │
   ▼
server.py        stdlib http.server JSON API + single HTML/JS page —
                 server holds all logic (same pattern as Formulate/
                 Gambit: browser sends a query, gets ranked results
                 back, zero search logic client-side)
   │
   ▼
cli.py           `trove build <dir>`, `trove search <query>`,
                 `trove serve`, `trove eval` — everything also usable
                 headless without the browser
```

## Feature list

**Required (4):**
1. **Tokenizer + inverted index** — real Porter stemming (implemented
   from scratch, not a stdlib/pip shortcut), stopword removal,
   positional postings, persisted to disk so indexing and querying are
   separate steps.
2. **BM25 ranking** — the actual Okapi BM25 formula (IDF with
   term-frequency saturation via k1 and document-length normalization
   via b), verified by hand-computed expected scores on a tiny fixture
   corpus in the test suite, not just "results look reasonable".
3. **Structured query language** — boolean AND/OR/NOT with parentheses
   and correct precedence, plus `"exact phrase"` queries resolved via
   positional-postings intersection (adjacent positions), plus `term*`
   prefix queries. A recursive-descent parser, not string-splitting
   hacks.
4. **Fuzzy / typo-tolerant search** — a from-scratch BK-tree indexed by
   Levenshtein edit distance over the full vocabulary; any query term
   absent from the vocabulary is corrected to its nearest neighbor(s)
   within a distance threshold before the query runs, and the UI shows
   what was corrected ("no matches for 'spreadhseet' — showing results
   for 'spreadsheet'").

**Stretch (3, ≥1 required by the gate):**
5. Search-as-you-type **autocomplete** via a trie over the vocabulary,
   frequency-ranked, exposed as a live JSON endpoint and wired into the
   UI's search box.
6. **Relevance snippets** — for every hit, extract and highlight the
   densest window of matched query terms in context (not just the
   first N characters of the doc), the way real search engines show
   result previews.
7. **Ranking-quality evaluator** — a small hand-labeled relevance set
   (queries → which past-build folders are actually relevant) and a
   `trove eval` command that computes Precision@5 and NDCG@5 against
   it, so BM25's quality is measured quantitatively, not eyeballed.

## Verification plan (Phase 5 preview)

- Unit tests for the Porter stemmer against known stemming pairs.
- Unit tests for Levenshtein distance and BK-tree lookup against
  brute-force distance computation.
- Hand-computed BM25 score check on a fixture corpus small enough to
  compute by hand.
- Boolean query parser tests (precedence, parentheses, phrase,
  negation) against expected doc-id sets on a fixture corpus.
- End-to-end demo script: build the index over this repo's own 36
  READMEs + LEDGER.md, run a battery of real queries (including a
  deliberate typo and a phrase query) against it, and assert the
  expected past project shows up in the top results.
- A *second*, independent fixture corpus (not this repo) to prove the
  engine is general-purpose, not overfit to its own demo data.
