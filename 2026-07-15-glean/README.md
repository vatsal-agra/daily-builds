# Glean

A full-text search engine built from scratch in pure Python: a hand-written
Porter stemmer, a positional inverted index with a real on-disk binary
format, a boolean/phrase/proximity query language, and Okapi BM25 ranking
with highlighted snippets.

**Status: Phase 5 (verification) complete — shipped.** All 4 required
features and all 3 stretch features are implemented, covered by a
111-test Python suite plus a 22-check `demo.sh` (unit tests, CLI query
walkthrough, persistence round trip, live JSON API, and a headless-browser
UI smoke test), all green. See `PLAN.md` for architecture and the full
feature list, and `REVIEW.md` for the Phase 3 adversarial-review writeup
(7 real bugs found and fixed).

Run the whole thing end to end with:

```
./demo.sh
```

## Try it now

```
python3 -m glean.cli demo-index -o glean.idx    # index the 50-article demo corpus
python3 -m glean.cli search "roman empire" -i glean.idx
python3 -m glean.cli stats -i glean.idx

python3 -m glean.cli serve --demo -i glean.idx  # interactive browser UI at http://127.0.0.1:8752/
```

Query syntax: bare words (`roman empire`, implicit OR), `AND`/`OR`/`NOT`,
`"exact phrase"`, parenthesized grouping, and `word1 NEAR/3 word2`
proximity search. A misspelled query with no results gets a "did you mean"
suggestion from the fuzzy (Levenshtein/BK-tree) index, both on the CLI and
in the browser UI, which also offers live autocomplete as you type.

To index your own text files instead of the demo corpus:

```
python3 -m glean.cli index /path/to/txt-or-md-files -o mine.idx
python3 -m glean.cli search "your query" -i mine.idx
```
