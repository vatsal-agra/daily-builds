# Trove

*Status: Phase 4 complete (stretch features + polish). Verification next.*

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

See [PLAN.md](./PLAN.md) for architecture and the full feature list, and
[REVIEW.md](./REVIEW.md) for the Phase 3 adversarial review — 8 real
bugs found by deliberately attacking the query parser and CLI with
malformed input (a query parser silently returning the *opposite* of
what `-(...)` asked for was the sharpest one), each with a reproduction,
a fix, and a regression test.

## Quick start

```
python3 -m trove.cli build .. --repo-history --out /tmp/trove.index.json
python3 -m trove.cli search "CDCL solver" --index /tmp/trove.index.json
python3 -m trove.cli search '"clause learning"' --index /tmp/trove.index.json
python3 -m trove.cli search "raft AND consensus" --index /tmp/trove.index.json
python3 -m trove.cli serve --index /tmp/trove.index.json    # interactive web UI at http://127.0.0.1:8765
```

(A fuzzy-correction example belongs in `demo.sh`, not here: this README
is itself part of the demo corpus, so a misspelled word written in it
would become real indexed content instead of staying a hypothetical
typo — try it live in the web UI instead.)

## Stretch features (Phase 4)

All three planned stretch features shipped, plus the web UI they're
wired into:

- **Autocomplete** — a from-scratch trie over the vocabulary
  (`trove/suggest.py`), ranked by document frequency, exposed at
  `/api/suggest` and wired into the search box's dropdown. It also now
  accelerates boolean `term*` prefix queries (a trie descent instead of
  the linear vocabulary scan flagged as an accepted limitation in
  `REVIEW.md`).
- **Relevance snippets** — `trove/snippet.py` finds the densest cluster
  of query-term hits in a matched document and renders that window with
  matches marked, instead of just the first N characters.
- **Ranking-quality evaluator** — `trove eval` computes Precision@5 and
  NDCG@5 against 14 hand-labeled queries over this repo's own history
  (`trove/default_judgments.json`). Measured result: **mean P@5 = 0.86,
  mean NDCG@5 = 0.96** — including honestly-surfaced imperfections (e.g.
  two unrelated same-named "Strata" projects rank near each other since
  they share the literal word "Strata"). Enforced as a regression test
  in `tests/test_evaluation.py`.
- **Web UI** — `trove serve` starts a stdlib `http.server` (no runtime
  dependency, same architecture as the CLI) at `http://127.0.0.1:8765`
  with live search, autocomplete, highlighted snippets, and inline
  query-error / fuzzy-correction messages. The browser holds zero search
  logic; every keystroke is a network round trip to the same `Engine`
  the CLI uses. All server-supplied text is rendered via `textContent`/
  DOM construction, never `innerHTML` string concatenation — verified
  both structurally (raw_tokens() strips `<`/`>` before anything reaches
  an index) and with a live document containing a literal `<script>`
  tag in `tests/test_server.py`.

## Tests

```
python3 -m unittest discover -s tests -v
```

126 unit tests covering the stemmer (differentially checked against
NLTK's Porter oracle), tokenizer, index (including the Phase 3
duplicate-`doc_id` fix), BM25 ranking (hand-verified against an
independent formula), the query parser/evaluator (including all eight
Phase 3 regression cases and trie-accelerated prefix queries), the
autocomplete trie, snippet extraction, the ranking-quality evaluator
(with a live regression threshold on real measured quality), the HTTP
server (including an XSS-safety check), the CLI end-to-end, the
`Engine` facade, and the Levenshtein/BK-tree fuzzy matcher.

Remaining work: a full verification pass (Phase 5) and final ship
polish (Phase 6) — tracked phase by phase in this README as the build
continues.
