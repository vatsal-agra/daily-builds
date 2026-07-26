# Phase 3 — Adversarial Review

Hostile pass over my own Phase 2 build: hand-crafted small corpora with known-answer
queries, boundary-condition inputs (empty query, all-stopword query, empty corpus,
malformed syntax), and a re-run of the self-indexing demo to check its claims are
actually true rather than merely plausible-looking.

## Method

- Canonical correctness check: ran all 75 word/stem pairs from Martin Porter's own
  published test vocabulary through `porter_stem` — this caught two real bugs before
  the review pass even started (see below), and now passes 75/75 exactly, including
  known "quirks" of the 1980 algorithm (`consensus` → `consensu`, `ray` → `rai`) that
  are faithful to the original spec rather than bugs to paper over.
- Hand-built 3-document corpora with a known ground truth, to test boolean/phrase/NOT
  logic against an answer I could verify by inspection, not just "did it not crash."
- Boundary inputs: empty query, whitespace-only query, all-stopword query, unbalanced
  quote, empty corpus (zero documents), a directory with zero matching files.
- Re-ran `glean demo` and manually checked whether each result was a *genuine*
  demonstration of the claimed capability, or an artifact of the demo corpus
  containing the test's own scaffolding.

## Bugs found and fixed

1. **CRITICAL (during stemmer validation, pre-review): crash on every word ending in
   `-ed`/`-ing`.** `porter_stem`'s Step 1b referenced a `step1b_extra` local that was
   only assigned inside the `elif` branches, not the `if word.endswith("eed")` branch —
   any word taking that first branch raised `UnboundLocalError`. Since `-ed`/`-ing` are
   among the most common English suffixes, this meant the analyzer crashed on a large
   fraction of real text. Fixed by initializing `step1b_extra = False` before the
   if/elif chain.

2. **MODERATE: pure-negation queries returned zero results.** `NOT chess` alone (no
   positive term) produced an empty candidate set, because the boolean resolver only
   ever seeded candidates from MUST or SHOULD clauses — a query built entirely of
   NOT clauses had nothing to subtract from. A user typing `NOT chess` reasonably
   expects "everything except chess docs," not silence. Fixed in `query.search()`:
   when there are no MUST and no SHOULD clauses but at least one MUST_NOT clause, the
   candidate set now falls back to the whole corpus (`index.docs.keys()`) before
   subtracting exclusions.

3. **MODERATE: fuzzy typo-correction could silently rewrite quoted phrases.** A
   `"quoted phrase"` is supposed to mean "this exact text," but the fuzzy-matching
   pass ran over every clause's terms indiscriminately, including phrase clauses —
   so a phrase with one misspelled word could get a *different* word substituted in
   and then be scored/filtered as if that substitution were the user's original
   phrase, with no indication anything had been changed. This breaks the "exact
   phrase" contract and could hide or distort results in a way a user has no way to
   notice. Fixed by restricting fuzzy expansion to bare `term` clauses only; phrase
   clauses now always mean exactly what was typed.

4. **MINOR (self-review, not a code bug but a misleading demo): the fuzzy-matching
   sample query in `glean demo` was a misspelling of "consensus" that happened to
   appear verbatim (as an example of a typo!) inside this very project's own
   `PLAN.md`. So the demo was "proving" fuzzy matching by exact-stem-matching its
   own planning document, not by genuinely correcting a typo against unrelated
   documents elsewhere in the corpus (e.g. Quorum's Raft consensus write-up, which
   is what the query was supposed to be about). Caught by manually inspecting *why*
   each demo result ranked where it did, not just checking that results existed.
   Replaced with a one-letter-dropped misspelling of "transposition" in
   `glean/cli.py`'s `sample_queries`, which correctly triggers fuzzy correction and
   surfaces Gambit's chess/transposition-table documentation — a real
   cross-document fuzzy match.

   **Recursion caught in this same review pass:** the first draft of this very
   paragraph spelled out that replacement typo literally, in this file — which,
   once committed, would have made *this document* the verbatim source the fuzzy
   query exact-matched against, reintroducing the identical bug one paragraph after
   describing it. Fixed by describing the typo instead of quoting it. Lesson: any
   prose that names a fuzzy-search demo's exact query text is itself part of the
   corpus once indexed, and needs the same scrutiny as the demo code.

## Verified clean (no fix needed)

- Empty query, whitespace-only query, and all-stopword queries (`"the a of"`) return
  a clean "no results" instead of crashing.
- Unbalanced quotes (`"raft leader` with no closing quote) degrade gracefully to a
  bare-word match rather than raising a parse error.
- An empty corpus (zero indexed documents) and a directory with zero matching
  extensions both index and search without division-by-zero or exceptions (BM25's
  average-document-length term is explicitly guarded).
- Incremental reindexing correctly re-analyzes changed files, reuses unchanged files
  (by mtime), and drops documents whose source file was deleted — verified by
  editing and deleting files between reindex runs and checking both the reported
  stats and that deleted content stops being searchable.
- A deleted/moved source file at query time degrades to `(source file unavailable)`
  in the snippet instead of crashing the CLI or the HTTP server.
- The BM25 idf formula (`log(1 + (N-df+0.5)/(df+0.5))`) never goes negative even for
  terms present in every document, so no document can get a negative relevance
  score.

## Addendum — a bug the adversarial review pass missed, caught by the test suite

Writing the Phase 5 test suite surfaced a real correctness bug that the hand-crafted
Phase 3 corpora happened not to expose:

5. **MODERATE: `A AND B` didn't actually require both `A` and `B`.** The parser only
   marked the term textually *after* `AND` as a MUST clause; the term before it (with
   no operator of its own) stayed a default SHOULD clause, which only adds to the
   score and never filters. So `chess AND bloom` — over a corpus where `bloom`
   appears in two unrelated documents and `chess` in a third, disjoint one — silently
   returned both `bloom` documents even though *neither* contained "chess". This
   passed Phase 3's `chess AND transposition` check purely by luck: in that corpus
   "transposition" alone was already selective enough to isolate the right document,
   so the missing filter on "chess" never showed up. A second, deliberately
   less-forgiving test (`chess AND bloom`, where the AND-left term is the *only*
   thing that should exclude two otherwise-matching documents) exposed it
   immediately. Fixed in `parse_query()`: when a clause's connector is `AND`, its
   immediate predecessor is now also forced into the MUST group, so both operands
   of an explicit AND are required. Lesson re-confirmed: a review corpus where a
   single term already disambiguates the right answer can hide a broken boolean
   operator right next to it — the fix was to test the operator in isolation, not
   just the end-to-end query.

## Not fixed (accepted, documented limitation)

- The Porter algorithm's known rough edges (`consensus`→`consensu`, `ray`→`rai`,
  apostrophes treated as consonants) are inherent to the 1980 algorithm as published,
  not implementation bugs — "fixing" them would mean implementing a different,
  later algorithm (e.g. Snowball/Porter2) under the same name, which is out of scope.
