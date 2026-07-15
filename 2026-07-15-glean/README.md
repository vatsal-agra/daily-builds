# Glean

A full-text search engine built from scratch in pure Python: a hand-written
Porter stemmer, a positional inverted index with a real on-disk binary
format, a boolean/phrase/proximity query language, and Okapi BM25 ranking
with highlighted snippets.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and covered by a 62-test suite (green), including a
differential oracle that cross-checks every boolean/phrase/proximity query
result against a brute-force scan of the raw token stream. See `PLAN.md`
for architecture and the full feature list.

## Try it now

```
python3 -m glean.cli demo-index -o glean.idx    # index the 50-article demo corpus
python3 -m glean.cli search "roman empire" -i glean.idx
python3 -m glean.cli stats -i glean.idx
```

Query syntax: bare words (`roman empire`, implicit OR), `AND`/`OR`/`NOT`,
`"exact phrase"`, parenthesized grouping, and `word1 NEAR/3 word2`
proximity search.

Stretch features (fuzzy search, autocomplete, interactive browser UI) and
final polish are still in progress — see `PLAN.md`.
