#!/usr/bin/env bash
# Sift end-to-end demo/verification script.
# Exercises every feature through the real CLI and the real HTTP server —
# no mocks. Exits non-zero if any check fails.
set -u

cd "$(dirname "$0")"

PASS=0
FAIL=0
TMP="$(mktemp -d)"
INDEX="$TMP/demo.sift"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1
    wait "$SERVER_PID" 2>/dev/null
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

check() {
  local desc="$1"
  local status="$2"
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $desc"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc"
    FAIL=$((FAIL + 1))
  fi
}

check_contains() {
  local desc="$1"
  local haystack="$2"
  local needle="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  [PASS] $desc"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc (expected to find: $needle)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== D1: unit test suite ==="
python3 -m unittest discover -s tests >"$TMP/unittest.log" 2>&1
check "123-test unittest suite passes" $?
tail -3 "$TMP/unittest.log" | sed 's/^/    /'

echo "=== D2: corpus generation is reproducible ==="
python3 corpus/generate_corpus.py >/dev/null
check "generate_corpus.py runs clean" $?
COUNT=$(ls corpus/*.txt | wc -l | tr -d ' ')
[ "$COUNT" = "40" ]
check "corpus has exactly 40 documents ($COUNT found)" $?

echo "=== D3: indexing ==="
OUT=$(python3 -m sift.cli index corpus -o "$INDEX" 2>&1)
check "index command exits 0" $?
check_contains "reports 40 indexed documents" "$OUT" "indexed 40 documents"

echo "=== D4: boolean queries ==="
OUT=$(python3 -m sift.cli search "mars rover" -i "$INDEX" --no-snippets)
check_contains "implicit AND finds Mars Rovers doc" "$OUT" "Mars Rovers"

OUT=$(python3 -m sift.cli search "python AND rust" -i "$INDEX" --no-snippets)
check "AND with no shared doc returns 0 (clean exit)" $?
check_contains "AND with no shared doc reports no results" "$OUT" "no results"

OUT=$(python3 -m sift.cli search "jazz OR counterpoint" -i "$INDEX" --no-snippets)
check_contains "OR finds jazz improvisation doc" "$OUT" "Jazz Improvisation"
check_contains "OR finds counterpoint doc" "$OUT" "Counterpoint"

OUT=$(python3 -m sift.cli search "mars NOT rover" -i "$INDEX" --no-snippets)
check_contains "NOT excludes the only doc with both terms" "$OUT" "no results"

echo "=== D5: phrase queries (true positional adjacency) ==="
OUT=$(python3 -m sift.cli search '"black hole"' -i "$INDEX" --no-snippets)
check_contains "phrase query finds Black Holes doc" "$OUT" "Black Holes"

OUT=$(python3 -m sift.cli search '"hole black"' -i "$INDEX" --no-snippets)
check_contains "reversed phrase order finds nothing" "$OUT" "no results"

echo "=== D6: wildcard / prefix queries ==="
OUT=$(python3 -m sift.cli search "quan*" -i "$INDEX" --no-snippets)
check_contains "quan* matches Quantum Mechanics doc" "$OUT" "Quantum Mechanics"

echo "=== D7: fuzzy queries + did-you-mean ==="
OUT=$(python3 -m sift.cli search "pytho~2" -i "$INDEX" --no-snippets)
check_contains "pytho~2 fuzzy-matches the Python doc" "$OUT" "Why Python Became"

OUT=$(python3 -m sift.cli search "quantumm" -i "$INDEX" --no-snippets)
check_contains "typo query offers a suggestion" "$OUT" "did you mean"
check_contains "suggestion is the real word, not operator noise" "$OUT" "quantum"

echo "=== D8: BM25 ranking sanity ==="
OUT=$(python3 -m sift.cli search "space" -i "$INDEX" --no-snippets)
check_contains "topical query surfaces a space doc" "$OUT" "Space"

echo "=== D9: snippets + highlighting ==="
OUT=$(python3 -m sift.cli search "black hole" -i "$INDEX")
check_contains "snippet output includes bracketed highlight markers" "$OUT" "**"

echo "=== D10: on-disk binary index format round-trips ==="
python3 - "$INDEX" <<'PYEOF'
import sys
from sift.storage import load_index
from sift.query import search
idx = load_index(sys.argv[1])
results = search(idx, '"black hole"')
assert len(results) == 1, f"expected 1 result, got {results}"
doc = idx.documents[results[0][0]]
assert "Black Holes" in doc.title, doc.title
print("roundtrip-ok")
PYEOF
check "loaded on-disk index reproduces correct search results" $?

echo "=== D11: error handling (bad input never crashes with a traceback) ==="
python3 -m sift.cli search "fox AND (" -i "$INDEX" >/dev/null 2>"$TMP/err.log"
[ $? -ne 0 ]
check "unbalanced parens exits non-zero" $?
check_contains "unbalanced parens gives a clean message, not a traceback" "$(cat "$TMP/err.log")" "query error"

python3 -m sift.cli search '"unclosed' -i "$INDEX" >/dev/null 2>"$TMP/err2.log"
check_contains "unterminated phrase gives a clean message" "$(cat "$TMP/err2.log")" "unterminated phrase"

python3 -m sift.cli search "fox" -i /nonexistent/path.sift >/dev/null 2>"$TMP/err3.log"
check_contains "missing index file gives a clean message" "$(cat "$TMP/err3.log")" "not found"

mkdir -p "$TMP/empty_corpus"
python3 -m sift.cli index "$TMP/empty_corpus" -o "$TMP/empty.sift" >/dev/null 2>"$TMP/err4.log"
check_contains "indexing an empty directory gives a clean message" "$(cat "$TMP/err4.log")" "no .txt"

echo "=== D12: interactive HTML server (real HTTP, real ranking engine) ==="
python3 -m sift.cli serve -i "$INDEX" -p 8231 >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
for i in $(seq 1 20); do
  curl -s -o /dev/null "http://127.0.0.1:8231/" && break
  sleep 0.2
done

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8231/")
[ "$STATUS" = "200" ]
check "GET / serves the HTML UI (200)" $?

BODY=$(curl -s "http://127.0.0.1:8231/api/search?q=black+hole")
check_contains "API returns the Black Holes doc" "$BODY" "Black Holes"
check_contains "API response includes a mark-highlighted snippet" "$BODY" "<mark>"

BODY=$(curl -s "http://127.0.0.1:8231/api/search?q=quantumm")
check_contains "API surfaces a suggestion for a typo'd query" "$BODY" "quantum"

BODY=$(curl -s "http://127.0.0.1:8231/api/stats")
check_contains "API stats report 40 indexed documents" "$BODY" "\"doc_count\": 40"

kill "$SERVER_PID" >/dev/null 2>&1
wait "$SERVER_PID" 2>/dev/null
SERVER_PID=""

echo
echo "================================================"
echo "  Sift demo: $PASS passed, $FAIL failed"
echo "================================================"

[ "$FAIL" -eq 0 ]
