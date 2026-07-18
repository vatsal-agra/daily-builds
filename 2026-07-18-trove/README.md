# Trove

*Status: Phase 2 complete (core build). Adversarial review next.*

A from-scratch full-text search engine — tokenizer, a faithful Porter
stemmer (differentially verified against NLTK's `ORIGINAL_ALGORITHM`
oracle over 5,000+ real words), an inverted index, Okapi BM25 ranking, a
real boolean/phrase/prefix query language, and a Levenshtein/BK-tree
fuzzy corrector for typos. Pure Python 3 stdlib — no runtime
dependencies.

Its demo corpus is this repository's own history: the READMEs of the 36
daily builds that came before it, made properly searchable for the
first time. It also works over any other directory of text/markdown
files (verified against an independent recipe-book fixture corpus in
the test suite).

See [PLAN.md](./PLAN.md) for architecture and the full feature list.

## Quick start

```
python3 -m trove.cli build .. --repo-history --out /tmp/trove.index.json
python3 -m trove.cli search "CDCL solver" --index /tmp/trove.index.json
python3 -m trove.cli search '"clause learning"' --index /tmp/trove.index.json
python3 -m trove.cli search "spreadhseet" --index /tmp/trove.index.json   # typo, auto-corrected
python3 -m trove.cli search "raft AND consensus" --index /tmp/trove.index.json
```

## Tests

```
python3 -m unittest discover -s tests -v
```

56 unit tests covering the stemmer (differentially checked against
NLTK's Porter oracle), tokenizer, index, BM25 ranking (hand-verified
against an independent formula), the query parser/evaluator, and the
Levenshtein/BK-tree fuzzy matcher (checked against brute force).

Remaining work: adversarial review, stretch features (autocomplete,
snippets, ranking-quality evaluator), web UI, polish, and full
verification — tracked phase by phase in this README as the build
continues.
