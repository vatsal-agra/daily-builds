# Sift

A full-text search engine built entirely from scratch in Python: tokenizer,
a real from-scratch Porter stemmer, an inverted index, a boolean/phrase
query engine, BM25 ranking, and BK-tree fuzzy matching — no search library
anywhere in the stack.

**Status: Phase 2 (core build) complete**, plus most stretch features
(wildcard search, snippets, on-disk binary index, HTML UI) are already
working end-to-end. See [PLAN.md](PLAN.md) for the architecture. Test suite
and adversarial review are next.

## Quick look

```
python3 corpus/generate_corpus.py        # write the 40-doc test corpus
python3 -m sift.cli index corpus -o demo.sift
python3 -m sift.cli search "mars rover" -i demo.sift
python3 -m sift.cli serve -i demo.sift   # interactive HTML UI at :8000
```
