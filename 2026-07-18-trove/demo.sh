#!/usr/bin/env bash
# Runnable demo/verification script for Trove.
#
# Exercises every shipped feature end-to-end against real data (this
# repository's own daily-build history) and fails loudly (set -e) if
# anything breaks. Run from inside 2026-07-18-trove/.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
INDEX=/tmp/trove-demo-index.json
PORT=8917

pass() { printf '  \033[32mOK\033[0m  %s\n' "$1"; }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

section "1. Unit test suite (126 tests)"
$PY -m unittest discover -s tests
pass "full unit test suite green"

section "2. Build the real repo-history index"
$PY -m trove.cli build .. --repo-history --out "$INDEX"
DOC_COUNT=$($PY -c "import json; print(json.load(open('$INDEX'))['N'])")
if [ "$DOC_COUNT" -lt 50 ]; then
  echo "expected at least 50 indexed documents, got $DOC_COUNT" >&2
  exit 1
fi
pass "indexed $DOC_COUNT real documents"

section "3. Feature: tokenizer + inverted index + BM25 ranking"
OUT=$($PY -m trove.cli search "CDCL solver" --index "$INDEX" --top 3)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -q "backjump\|conflux\|crux\|resolvent" || { echo "expected a CDCL solver project in top 3" >&2; exit 1; }
pass "BM25-ranked free-text search finds a real relevant project"

section "4. Feature: boolean query language (AND / OR / NOT)"
OUT=$($PY -m trove.cli search "raft AND consensus" --index "$INDEX" --top 3)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -q "quorum" || { echo "expected Quorum for 'raft AND consensus'" >&2; exit 1; }
pass "AND query narrows correctly"

OUT=$($PY -m trove.cli search "quantum OR chess" --index "$INDEX" --top 10)
echo "$OUT" | grep -q "qsim" || { echo "expected qsim in OR results" >&2; exit 1; }
echo "$OUT" | grep -q "gambit" || { echo "expected gambit in OR results" >&2; exit 1; }
pass "OR query unions correctly"

section "5. Feature: phrase query (positional adjacency)"
OUT=$($PY -m trove.cli search '"clause learning"' --index "$INDEX" --top 5)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -qi "cdcl\|backjump\|conflux\|crux\|resolvent" || { echo "expected a CDCL project for the phrase query" >&2; exit 1; }
pass "phrase query requires adjacency, finds real matches"

section "6. Feature: prefix query (term*)"
OUT=$($PY -m trove.cli search "consen*" --index "$INDEX" --top 5)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -q "quorum" || { echo "expected quorum for prefix 'consen*'" >&2; exit 1; }
pass "prefix query matches"

section "7. Feature: fuzzy typo correction"
# "consenus" is a deliberate misspelling of "consensus" -- long enough
# (9 chars) to earn the auto-fuzzy threshold's distance-2 slack (short
# words under 4 chars deliberately get none, per the Phase 3 review).
TYPO="consenus"
OUT=$($PY -m trove.cli search "$TYPO" --index "$INDEX" --top 3)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -q "no match for" || { echo "expected a fuzzy-correction message" >&2; exit 1; }
echo "$OUT" | grep -q "quorum" || { echo "expected quorum after fuzzy correction" >&2; exit 1; }
pass "fuzzy correction repairs a real typo and finds the right project"

section "8. Feature: negation, including the Phase 3 -(...) / -\"...\" fix"
OUT=$($PY -m trove.cli search 'solver -chess' --index "$INDEX" --top 5)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -qi "gambit" && { echo "chess ('gambit') should have been excluded by -chess" >&2; exit 1; }
pass "bare -word negation excludes correctly"

# The sharpest Phase 3 finding: -(...) used to silently drop the '-' and
# return the *positive* group -- the exact opposite of what was asked.
POS=$($PY -m trove.cli search '(cdcl AND solver)' --index "$INDEX" --top 50 | grep -c '^\s*[0-9]')
NEG=$($PY -m trove.cli search '-(cdcl AND solver)' --index "$INDEX" --top 50 | grep -c '^\s*[0-9]')
echo "  '(cdcl AND solver)' matched $POS docs; '-(cdcl AND solver)' matched $NEG docs"
if [ "$POS" -eq "$NEG" ]; then
  echo "negated group returned the same count as the positive group -- Phase 3 regression!" >&2
  exit 1
fi
pass "fused -(...) negation returns the complement, not the positive group"

section "9. Feature: ranking-quality evaluator"
OUT=$($PY -m trove.cli eval --index "$INDEX")
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -q "^MEAN" || { echo "expected a MEAN summary line from trove eval" >&2; exit 1; }
pass "eval produces Precision@5 / NDCG@5 against real judgments"

section "10. Feature: web UI (server + API)"
$PY -m trove.cli serve --index "$INDEX" --port "$PORT" >/tmp/trove-demo-server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for i in $(seq 1 20); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/stats"; then break; fi
  sleep 0.2
done
STATS=$(curl -s "http://127.0.0.1:$PORT/api/stats")
echo "  /api/stats -> $STATS"
echo "$STATS" | grep -q "\"documents\": $DOC_COUNT" || { echo "server stats mismatch" >&2; exit 1; }

SEARCH_JSON=$(curl -s "http://127.0.0.1:$PORT/api/search?q=CDCL+solver&top=3")
echo "  /api/search -> $(echo "$SEARCH_JSON" | head -c 160)..."
echo "$SEARCH_JSON" | grep -q "\"error\": null" || { echo "server search returned an error" >&2; exit 1; }

SUGGEST_JSON=$(curl -s "http://127.0.0.1:$PORT/api/suggest?prefix=quo")
echo "  /api/suggest -> $SUGGEST_JSON"
echo "$SUGGEST_JSON" | grep -q "quorum" || { echo "expected 'quorum' suggestion for prefix 'quo'" >&2; exit 1; }

HOMEPAGE=$(curl -s "http://127.0.0.1:$PORT/")
echo "$HOMEPAGE" | grep -q "<title>Trove</title>" || { echo "home page did not render" >&2; exit 1; }

kill $SERVER_PID 2>/dev/null || true
trap - EXIT
pass "web UI serves the page and all three API endpoints correctly"

section "11. Feature: general-purpose engine (independent second corpus)"
OUT=$($PY -m trove.cli build tests/fixtures/corpus_b --out /tmp/trove-demo-corpus-b.json)
echo "  $OUT"
OUT=$($PY -m trove.cli search "sourdough bread" --index /tmp/trove-demo-corpus-b.json --top 2)
echo "$OUT" | sed 's/^/  /'
echo "$OUT" | grep -qi "sourdough" || { echo "expected the sourdough recipe to match" >&2; exit 1; }
pass "engine works over a completely independent, non-software corpus"

rm -f "$INDEX" /tmp/trove-demo-corpus-b.json /tmp/trove-demo-server.log

echo
echo "=========================================="
echo " All Trove features verified successfully."
echo "=========================================="
