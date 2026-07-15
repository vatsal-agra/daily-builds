# Phase 3 — Adversarial Review

Hostile pass over the Phase 2 core build: fed the engine malformed input,
pathological strings, and queries whose text doesn't tokenize the way a
naive implementation would assume. Every issue below was reproduced with a
standalone script before being fixed, and every fix has a regression test.

## Issues found and fixed

1. **CRITICAL — titles were never searchable.** `InvertedIndex.add_document`
   only analyzed the `text` argument, never `title`. A search for `cry`
   against the article titled "Why Onions Make You Cry" (whose body uses
   "tears", not "cry") returned nothing, and `NEAR/k` queries anchored on a
   title word silently failed. Fixed by indexing `f"{title}. {text}"` as
   one combined stream, so titles are part of the searchable content (and,
   as a side effect, can appear in snippets, which is the expected
   behavior of a real search engine). Covered by
   `test_index.InvertedIndexTests.test_title_is_searchable` and the updated
   `test_empty_body_still_indexes_title`.

2. **CRITICAL — `term NOT term2` silently returned the wrong result set.**
   The query grammar treated any unmarked gap between two clauses as an
   implicit OR, including the gap before a bare `NOT`. So `football NOT
   basketball` parsed as `football OR (NOT basketball)` — matching nearly
   every document in the corpus instead of "football, excluding
   basketball." Fixed by special-casing an implicit `NOT` gap as `AND`
   (matching how a leading `-term` normally works in search boxes).
   Covered by the differential oracle battery in `test_query.py`
   (`"football NOT basketball"`, `"NOT basketball"`).

3. **HIGH — parenthesized queries containing no space before `)` failed to
   parse.** The lexer's catch-all token pattern was `\S+`, which happily
   swallowed an adjacent close-paren (`bread)` lexed as one token instead
   of `bread` + `)`). Any query like `cooking AND (pasta OR bread)` raised
   a spurious "expected RPAREN" error, and — worse — a genuinely unbalanced
   query like `cat AND dog)` was *not* flagged as invalid, because the
   stray `)` got absorbed into the word token and never became a real
   `RPAREN` token to trip the balance check. Fixed by excluding `(`/`)`
   from the catch-all pattern (`[^\s()]+`). Covered by
   `test_battery` (parenthesized queries) and
   `test_unbalanced_close_paren`.

4. **HIGH — hyphenated/apostrophe'd query words could never match.** The
   indexer's tokenizer splits `"well-known"` into two tokens, `well` and
   `known` (same for `"don't"` -> `don`, `t`), but the query parser treated
   a bare word token as a single, monolithic term without re-running it
   through the same tokenizer. Since `"well-known"` (with the hyphen) was
   never itself stored as a term, searching for `well-known` against text
   that literally contains "well-known" returned zero results — a
   correctness bug a user would hit constantly and never understand.
   Fixed by routing every bare WORD token through the tokenizer first: a
   single sub-word becomes a `TermNode` as before, multiple sub-words
   become an (already-existing) `PhraseNode`, and zero sub-words (e.g. a
   query of just `----`) now cleanly match nothing instead of crashing or
   silently building a nonsense term. Covered by
   `test_hyphenated_word_matches_as_implicit_phrase`,
   `test_apostrophe_word_matches_as_implicit_phrase`, and
   `test_punctuation_only_word_matches_nothing_not_crashes`.

5. **MEDIUM — an unterminated `"phrase` was silently treated as a garbage
   word instead of raising a syntax error.** With no closing quote, the
   lexer's catch-all pattern absorbed the stray `"` into an ordinary word
   token (`"cat`), which then parsed "successfully" as a term that could
   never match anything — a silent, confusing failure instead of a clear
   error message. Fixed by rejecting an odd number of `"` characters up
   front with a specific `QuerySyntaxError`. Covered by
   `test_unterminated_phrase`.

6. **MEDIUM — a long run of the letter 'y' could crash the stemmer with a
   `RecursionError`.** `_is_consonant` classified consecutive `y`s by
   recursing on the previous letter, so a word made of thousands of `y`s
   (plausible from an accidentally-indexed binary file, or just a hostile
   input) blew the Python call stack. Fixed by replacing the self-recursion
   with an iterative left-to-right scan that computes the exact same
   alternating consonant/vowel classification. Covered by
   `test_no_recursion_error_on_long_y_run` (5,000 `y`s).

7. **LOW — `--top-k -1` silently used Python's "all but the last result"
   slice semantics** (`scored[:-1]`) instead of erroring or returning
   nothing, because `list[:top_k]` treats a negative index as "from the
   end." A user who mistyped a negative count would get a plausible-looking
   but subtly wrong result list. Fixed at both layers: the CLI now rejects
   `--top-k < 0` with a clear error, and `SearchEngine.search` itself
   clamps `top_k` to `>= 0` so any other caller (including the Phase 4
   HTTP server) can't hit the same slice trap via a malformed request
   parameter. Covered by `test_negative_top_k_clamped_not_slice_wrapped`
   and the CLI-level manual check.

## Verification after fixes

- Full suite: 77/77 tests green, including a 300-query randomized fuzz test
  (`test_randomized_fuzz_against_oracle`) that builds random AND/OR/NOT/
  NEAR/paren/phrase query trees over real corpus vocabulary and checks
  every one against a brute-force oracle that re-scans each document's raw
  token stream — independent of the postings-based execution path.
- Manually re-verified every CLI error path (missing index file, corrupt
  index file, a directory passed as an index path, invalid query syntax,
  negative/zero `--top-k`) prints a clean one-line error and exits 1 — no
  raw tracebacks reach the terminal.
- Manually re-ran the exact repro script for each of the 7 issues above
  after its fix landed; none reproduce.
