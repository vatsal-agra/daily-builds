# Glean — a full-text search engine built from scratch

## Concept

Every major search engine — Lucene, Elasticsearch, Google circa 1998 — sits
on the same three ideas: an **inverted index** mapping terms to the
documents (and positions) they occur in, a **query engine** that combines
postings lists with set algebra and positional intersection, and a
**ranking function** that scores relevance instead of just returning an
unordered match set. This project builds all three from first principles in
pure Python: a tokenizer with a hand-written Porter stemmer, a positional
inverted index with a real on-disk binary format, a boolean/phrase/proximity
query language, and Okapi BM25 ranking with highlighted snippets. Stretch
goals add typo-tolerant fuzzy matching (Levenshtein + BK-tree) and
prefix-based autocomplete (trie), then wrap the whole thing in a
server-backed interactive search UI.

## Why it's interesting

Information retrieval is one of the few CS subfields where the "obvious"
approach (grep every document for every query) is asymptotically wrong, and
the fix — invert the index so you look up terms, not documents — is a
genuine conceptual leap with 50 years of refinement behind it (positional
indexes for phrase queries, BM25's document-length normalization, trigram/
edit-distance indexes for fuzzy matching). It's algorithmically rich,
independently verifiable (every ranking and boolean result can be checked
against a brute-force linear scan oracle), and produces something
immediately tactile: type a query, watch ranked, highlighted results come
back in milliseconds over real text.

## Architecture

```
glean/
  tokenizer.py   analyzer pipeline: Unicode word splitting, casefolding,
                 stopword filtering, hand-written Porter stemmer
  index.py       InvertedIndex: term -> postings (doc_id -> sorted positions),
                 document store (id/title/path/text/length), incremental
                 add_document, custom binary on-disk format (build/load)
  query.py       query language parser (bare terms, "phrase", AND/OR/NOT,
                 NEAR/k proximity, term~ fuzzy, term* prefix) + execution
                 engine: postings-list set algebra + positional intersection
  rank.py        Okapi BM25 scorer (configurable k1/b), TF-IDF cosine as a
                 second scorer for comparison, snippet extraction with
                 highlighted query terms
  fuzzy.py       Levenshtein edit distance (DP) + BK-tree index over the
                 vocabulary for "did you mean" / typo-tolerant matching
  trie.py        prefix trie over the vocabulary for autocomplete
  corpus/        hand-written demo corpus (~50 short articles, 5 topics)
  server.py      stdlib http.server JSON API backing the browser UI
                 (all ranking/parsing logic stays server-side)
  static/        single-file HTML/CSS/JS search UI (search-as-you-type,
                 highlighted snippets, autocomplete dropdown, facets)
  cli.py         `glean` CLI: index / search / serve / stats / demo / test
tests/           unit + differential + fuzz test suite
demo.sh          build corpus -> index -> full test suite -> CLI walkthrough
                 -> headless-browser UI smoke test
```

## Feature list

**Required (4):**
1. **Analyzer pipeline** — Unicode-aware tokenizer, case-folding, stopword
   filtering, and a from-scratch Porter stemming algorithm (the real
   1980 algorithm, not a stub — verified against the official Porter test
   vector list).
2. **Positional inverted index** — term -> postings (doc_id -> sorted term
   positions) built by streaming a document corpus, with per-document
   length tracking (for BM25 normalization), incremental `add_document`,
   and a real on-disk binary format (`build`/`load` round-trip, not just
   pickling).
3. **Boolean + phrase + proximity query engine** — a small query language
   (`word`, `"exact phrase"`, `AND`/`OR`/`NOT`, `word1 NEAR/3 word2`)
   compiled to postings-list set algebra and positional intersection,
   verified against a brute-force linear-scan oracle over the corpus.
4. **BM25 ranking with highlighted snippets** — Okapi BM25 scoring
   (configurable `k1`/`b`) producing a ranked top-K result list, each with
   an extracted, query-term-highlighted snippet.

**Stretch (3, aim to ship all):**
5. **Fuzzy / typo-tolerant search** — hand-written Levenshtein DP + a
   BK-tree index over the vocabulary, giving edit-distance-bounded term
   matching and "did you mean" suggestions for zero-result queries.
6. **Prefix autocomplete** — a trie over the vocabulary powering
   search-as-you-type suggestions.
7. **Interactive server-backed search UI** — a single HTML page talking to
   a real Python `http.server` backend (no client-side ranking logic, same
   pattern as prior server-backed daily builds), with live search,
   highlighted snippets, an autocomplete dropdown, and index stats.

## Verification strategy

- Porter stemmer checked against the canonical vocabulary/output test-vector
  pair published with the original algorithm.
- Boolean/phrase/proximity queries checked against a brute-force oracle that
  re-tokenizes and linearly scans the raw corpus for every query.
- BM25 scores checked against a hand-computed reference implementation over
  a small fixed corpus with known term frequencies.
- Levenshtein distance checked against `difflib`-independent DP recurrence
  test vectors and symmetry/triangle-inequality properties.
- Index binary format checked with a build -> load -> re-query round trip
  that must return identical results to the in-memory index.
