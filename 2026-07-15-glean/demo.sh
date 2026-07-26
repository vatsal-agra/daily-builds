#!/usr/bin/env bash
# Glean end-to-end verification: unit suite -> CLI walkthrough -> live server
# + headless-browser UI smoke test. Exits non-zero on the first failure.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
IDX="$(mktemp -d)/demo.idx"
SERVER_LOG="$(mktemp -d)/server.log"
SERVER_PID=""

check() {
  local desc="$1"
  shift
  if "$@" >/tmp/glean-demo-check.out 2>&1; then
    echo "  ok  - $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL  - $desc"
    sed 's/^/        /' /tmp/glean-demo-check.out
    FAIL=$((FAIL + 1))
  fi
}

check_output() {
  local desc="$1" pattern="$2"
  shift 2
  local out
  out="$("$@" 2>&1)"
  if echo "$out" | grep -qF "$pattern"; then
    echo "  ok  - $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL  - $desc (expected to find: $pattern)"
    echo "$out" | sed 's/^/        /'
    FAIL=$((FAIL + 1))
  fi
}

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

echo "=== 1. Python test suite ==="
check "111-test suite is green" python3 -m unittest discover -s tests

echo
echo "=== 2. CLI: indexing ==="
check "demo-index builds an index" python3 -m glean.cli demo-index -o "$IDX"
check_output "stats reports 50 documents" '"documents": 50' python3 -m glean.cli stats -i "$IDX"

CUSTOM_DIR="$(mktemp -d)"
echo "The quick brown fox jumps over the lazy dog in the forest." > "$CUSTOM_DIR/fox.txt"
echo "Bread rises in the oven because yeast releases carbon dioxide gas." > "$CUSTOM_DIR/bread.md"
CUSTOM_IDX="$(mktemp -d)/custom.idx"
check "index builds from a custom directory of .txt/.md files" \
  python3 -m glean.cli index "$CUSTOM_DIR" -o "$CUSTOM_IDX"
check_output "search finds content indexed from a custom directory" "fox" \
  python3 -m glean.cli search "fox" -i "$CUSTOM_IDX"

echo
echo "=== 3. CLI: query language ==="
check_output "bare-word query" "The Fall of the Roman Empire" \
  python3 -m glean.cli search "roman empire" -i "$IDX"
check_output "exact phrase query" "The Printing Press and Its Impact" \
  python3 -m glean.cli search "\"printing press\"" -i "$IDX"
check_output "AND query" "The Rules of Chess Notation" \
  python3 -m glean.cli search "chess AND notation" -i "$IDX"
check_output "NOT query excludes the right document" "How the Offside Rule Works" \
  python3 -m glean.cli search "football NOT basketball" -i "$IDX" -k 5
check_output "NEAR/k proximity query" "Why Onions Make You Cry" \
  python3 -m glean.cli search "onion NEAR/3 cry" -i "$IDX"
check_output "parenthesized grouping" "The History of Pasta" \
  python3 -m glean.cli search "cooking AND (pasta OR bread)" -i "$IDX"
check_output "hyphenated query word matches as an implicit phrase" "The Evolution of the Basketball Three-Pointer" \
  python3 -m glean.cli search "three-pointer" -i "$IDX"
check_output "malformed query prints a clean error, not a traceback" "query error" \
  python3 -m glean.cli search "(unterminated" -i "$IDX"
check_output "did-you-mean suggestion on a misspelled query" "did you mean: photosynthesis" \
  python3 -m glean.cli search "photosinthesis" -i "$IDX"

echo
echo "=== 4. Persistence round trip ==="
python3 - "$IDX" <<'PYEOF'
import sys
from glean.engine import SearchEngine
path = sys.argv[1]
before = SearchEngine.load(path)
before_results = [(r.doc_id, round(r.score, 6)) for r in before.search("roman empire")]
before.save(path)  # re-save, then re-load, and confirm identical results
after = SearchEngine.load(path)
after_results = [(r.doc_id, round(r.score, 6)) for r in after.search("roman empire")]
assert before_results == after_results, (before_results, after_results)
assert before_results, "expected at least one result"
print("round trip OK:", before_results)
PYEOF
ROUNDTRIP_RC=$?
if [ "$ROUNDTRIP_RC" -eq 0 ]; then
  echo "  ok  - index save -> load -> re-query round trip matches"
  PASS=$((PASS + 1))
else
  echo "FAIL  - index save -> load -> re-query round trip matches"
  FAIL=$((FAIL + 1))
fi

echo
echo "=== 5. Live server + JSON API ==="
python3 -m glean.cli serve --demo -i "$IDX" -p 8752 > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8752/api/stats && break
  sleep 0.3
done

check_output "GET / serves the search page" "Glean" curl -s http://127.0.0.1:8752/
check_output "GET /api/stats reports the corpus size" '"documents": 50' curl -s http://127.0.0.1:8752/api/stats
check_output "GET /api/search returns ranked, highlighted results" "<mark>Roman</mark>" \
  curl -s "http://127.0.0.1:8752/api/search?q=roman+empire"
check_output "GET /api/autocomplete suggests a real word" "photosynthesis" \
  curl -s "http://127.0.0.1:8752/api/autocomplete?q=phot"
check_output "GET /api/search with bad syntax returns HTTP 400" "400" \
  curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8752/api/search?q=(unterminated"
check_output "unknown route returns HTTP 404" "404" \
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8752/nope

echo
echo "=== 6. Headless-browser UI smoke test ==="
if command -v node >/dev/null 2>&1; then
  check "browser-driven UI walkthrough (search, highlight, autocomplete, did-you-mean, error handling)" \
    node tests/ui_smoke.mjs
else
  echo "  skip - node not available"
fi

echo
echo "=== Summary ==="
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
