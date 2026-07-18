# Trove

*Status: shipped (all 6 build phases complete).*

A full-text search engine built entirely from scratch in pure Python 3
(stdlib only — no NumPy, no Whoosh, no Elasticsearch, no `pip install`
anything) — the same architecture behind Lucene and Elasticsearch,
implemented from first principles: a from-scratch Porter stemmer, an
inverted index with positional postings, Okapi BM25 ranking, a real
boolean/phrase/prefix query language with a hand-written recursive-descent
parser, a Levenshtein/BK-tree fuzzy typo corrector, a trie-based
autocomplete engine, relevance-snippet extraction, and a quantitative
ranking-quality evaluator — behind a CLI and a server-backed interactive
web UI.

Its demo corpus isn't synthetic filler: it's this repository's own
history. `daily-builds/` holds 36 past projects, each with a substantial
README — until today, searchable only by `grep`, which knows nothing
about relevance, ranking, phrases, or typos. Trove makes that whole
archive properly searchable, and also works as a general-purpose engine
over any directory of text/markdown files (verified against an
independent, non-software fixture corpus in the test suite and in
`demo.sh`).

## Why this, today

Every other "from-scratch X" build in this repo has picked one deep
algorithm and built a product around it — SAT solvers, path tracers, a
spreadsheet engine, a SQL engine, a version-control system, a vector
search engine (`2026-06-27-vecnn`, which does *neural* embedding search
— HNSW over vectors). Classical full-text search is a different kind of
challenge: it's a *pipeline* of several well-known algorithms (an
edit-distance automaton, TF-IDF/BM25 statistics, a trie, boolean query
evaluation over postings lists) that only becomes a real search engine
when the interfaces between them are correct — get that wrong and you
get an engine that's "basically working" but ranks garbage first, or
silently returns the wrong answer to a valid query. That composition
risk is exactly what the adversarial-review phase caught (see below).
It's also a genuinely new domain for this repo, complementary to VecNN
rather than a repeat of it.

## Quick start

```
python3 -m trove.cli build .. --repo-history --out /tmp/trove.index.json
python3 -m trove.cli search "CDCL solver" --index /tmp/trove.index.json
python3 -m trove.cli search '"clause learning"' --index /tmp/trove.index.json
python3 -m trove.cli search "raft AND consensus" --index /tmp/trove.index.json
python3 -m trove.cli eval --index /tmp/trove.index.json
python3 -m trove.cli serve --index /tmp/trove.index.json    # web UI at http://127.0.0.1:8765
```

(No fuzzy-typo example is written out here on purpose: this README is
itself part of the demo corpus once built, so a literal misspelled word
placed in it would become real indexed content instead of staying a
hypothetical typo. Try one live in the web UI — e.g. a misspelling of
"consensus" — or see `demo.sh`.)

Or point it at anything else:

```
python3 -m trove.cli build /path/to/some/notes --out /tmp/notes.index.json
python3 -m trove.cli search "your query" --index /tmp/notes.index.json
```

## Full feature list

**Core (required):**
1. **Tokenizer + inverted index** — a faithful from-scratch Porter
   stemmer (differentially verified against NLTK's `PorterStemmer` in
   `ORIGINAL_ALGORITHM` mode across every one of the ~5,100 unique words
   in this repo's real READMEs, 100% match), stopword filtering,
   positional postings, JSON persistence. Markdown files are
   automatically split on `## ` headers so a single file like
   `LEDGER.md` (36+ project write-ups) indexes as many separate,
   individually-rankable documents.
2. **Okapi BM25 ranking** — the real formula (term-frequency saturation
   via `k1`, length normalization via `b`), hand-verified in
   `tests/test_ranking.py` against an independently-written textbook
   formula on a fixture index with known term frequencies.
3. **Boolean/phrase/prefix query language** — `AND` / `OR` / `NOT` with
   correct precedence and parentheses, implicit `AND` between adjacent
   terms, `"exact phrase"` via positional-postings adjacency, `term*`
   prefix matching — a hand-written recursive-descent parser, not
   string-splitting.
4. **Fuzzy typo correction** — a from-scratch BK-tree over the full
   vocabulary (Levenshtein edit distance, also from scratch), with a
   length-scaled auto threshold (no correction under 4 characters, where
   it would just produce false positives; 1 edit for 4-5 chars; 2 for
   longer) so a longer misspelled word still resolves to the intended
   term without short words corrupting into unrelated ones.

**Stretch:**
5. **Autocomplete** — a from-scratch trie over the vocabulary, ranked by
   document frequency, powering both the web UI's live suggestion
   dropdown and (as a nice side effect) making `term*` prefix queries a
   trie descent instead of a linear vocabulary scan.
6. **Relevance snippets** — finds the *densest cluster* of query-term
   hits in a matched document and renders that window with matches
   marked, not just the first N characters of the document.
7. **Ranking-quality evaluator** — `trove eval` computes Precision@5 and
   NDCG@5 against 14 hand-labeled relevance judgments over this repo's
   real history. Measured, not assumed: **mean P@5 = 0.86, mean NDCG@5 =
   0.96**, enforced as a regression floor in `tests/test_evaluation.py`.
   The imperfections are real and left visible rather than curated away
   — e.g. two unrelated same-named "Strata" projects (an LSM-tree KV
   store and a separate VCS) rank near each other because they
   genuinely share the word "Strata".
8. **Web UI** — `trove serve` starts a dependency-free `http.server`
   with live search, autocomplete, highlighted snippets, and inline
   error/correction messages. The browser holds zero search logic —
   every keystroke is a network round trip to the same `Engine` the CLI
   uses (the same architecture as this repo's Formulate and Gambit
   builds). All server-supplied text renders via `textContent`/DOM
   construction, never `innerHTML`; verified both structurally (the
   tokenizer strips `<`/`>` before anything reaches the index, so a
   literal `<script>` tag in a document can't even survive into a
   snippet) and with a live XSS-payload document in `tests/test_server.py`.

## Adversarial review

Phase 3 (`REVIEW.md`) deliberately attacked the query parser and CLI
with malformed, adversarial, and boundary input and found 8 real bugs,
each reproduced, fixed, and covered by a regression test — the sharpest
was a **silent-wrong-answer bug**: `-(fox AND lazy)` returned the same
result as the *positive* `(fox AND lazy)` instead of its complement,
because the lexer couldn't tokenize `-` fused to `(` or `"`. Others
included a duplicate-`doc_id` crash risk (realistic for this repo
specifically, which already has several same-named projects from
parallel sessions), an unterminated-quote query silently changing
meaning instead of erroring, unbounded recursion depth on pathological
input, Python's negative-slice semantics silently mangling `--top -1`,
and fixed-distance fuzzy correction producing nonsense on short words.

## Tests & verification

```
python3 -m unittest discover -s tests -v   # 126 unit tests
./demo.sh                                    # full end-to-end verification
```

`demo.sh` is an 11-section, fail-loud (`set -e`) script that builds the
real repo-history index and drives every feature against it through the
actual CLI and a live server subprocess — including a direct regression
check that `-(cdcl AND solver)` now returns the complement of
`(cdcl AND solver)`, not a silent copy of it.

## Stack

Pure Python 3 stdlib for every runtime code path (`re`, `json`,
`http.server`, `math`, `argparse`) — zero pip dependencies to run or
ship. NLTK is used *only* as a dev-time differential oracle in the test
suite to independently verify the from-scratch Porter stemmer, the same
way past builds in this repo cross-checked against real `git` or
OpenSSL; it is never imported by any shipped code path.

## Where a human could take this next

- **Real ranking eval at scale**: 14 hand-labeled queries is enough to
  catch regressions, not enough to tune BM25's `k1`/`b` with confidence
  — a larger judged set (or click-through data from real use) would
  make `trove eval` a genuine tuning tool instead of a smoke test.
- **Persistent index updates**: the index is build-once, read-many;
  incremental updates (add/remove a document without a full rebuild)
  would make this usable as a live tool over a folder that keeps
  changing, like a git pre-commit hook that reindexes touched files.
- **Ranking beyond BM25**: field boosting (weight a title match higher
  than a body match), phrase-proximity scoring, or a learned re-ranker
  over BM25's candidate set.
- **Query language extras**: fielded search (`title:formulate`), range
  queries, and multi-word fuzzy phrases (currently fuzzy correction
  applies per-term but phrase adjacency requires literal stemmed
  matches).
- **Scale-out**: sharding the inverted index across multiple processes
  for corpora too large for one process's memory — the postings-list
  design here would extend naturally to a merge-based distributed query.
