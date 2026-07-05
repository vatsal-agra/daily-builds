# Sift

A full-text search engine built entirely from scratch in Python: a
tokenizer, a real from-scratch Porter stemmer, an inverted index, a
boolean/phrase query engine, BM25 ranking, and BK-tree fuzzy matching — no
search library anywhere in the stack.

**Status: shipped.** All 4 required features and all 4 stretch features are
implemented and working end-to-end, adversarially reviewed, covered by 123
unit tests plus a 30-check `demo.sh` that drives the real CLI and a real
running HTTP server. See [PLAN.md](PLAN.md) for the architecture and
[REVIEW.md](REVIEW.md) for the adversarial-review findings.

## Quick look

```
python3 corpus/generate_corpus.py        # write the 40-doc test corpus (already committed)
python3 -m sift.cli index corpus -o demo.sift
python3 -m sift.cli search "mars rover" -i demo.sift
python3 -m sift.cli search "black AND NOT space" -i demo.sift --no-snippets
python3 -m sift.cli search "quantumm" -i demo.sift   # typo -> "did you mean: quantum?"
python3 -m sift.cli serve -i demo.sift               # interactive HTML UI at :8000
python3 -m sift.cli demo                             # build + run a canned query tour
```

## Query syntax

- `AND` / `OR` / `NOT`, case-insensitive, with `(` `)` grouping
- `"exact phrase"` — matched via true positional adjacency, not substring search
- `prefix*` — wildcard/prefix expansion via a trie
- `term~2` — fuzzy match within edit distance 2 via a BK-tree (also powers "did you mean")

## Tests

```
python3 -m unittest discover -s tests   # 123 unit tests
./demo.sh                               # 30-check end-to-end walkthrough (CLI + live HTTP server)
```
