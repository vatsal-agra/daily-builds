#!/usr/bin/env bash
# Glean demo: runs the full test suite, then exercises every feature end-to-end
# via the CLI and the HTTP API/UI, on a throwaway corpus plus the self-indexing demo.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=python3
PASS="\033[32mPASS\033[0m"
FAIL="\033[31mFAIL\033[0m"
FAILED=0

check() {
  local desc="$1"
  shift
  if "$@" >/tmp/glean_demo_check.log 2>&1; then
    echo -e "  $PASS  $desc"
  else
    echo -e "  $FAIL  $desc"
    sed 's/^/       /' /tmp/glean_demo_check.log
    FAILED=1
  fi
}

echo "== 1. Unit test suite (81 tests: analyzer, index, query, fuzzy, crawler, snippet, CLI) =="
$PY -m unittest discover -s tests
echo

echo "== 2. CLI walkthrough on a throwaway corpus =="
DEMO_DIR="$(mktemp -d)"
trap 'rm -rf "$DEMO_DIR"' EXIT
cat > "$DEMO_DIR/raft.md" <<'EOF'
# Raft Consensus
A deterministic raft consensus simulator with a bloom filter cache.
EOF
cat > "$DEMO_DIR/chess.md" <<'EOF'
# Chess Engine
A chess engine with alpha-beta search and a transposition table.
EOF

check "index builds successfully"      $PY -m glean.cli index "$DEMO_DIR"
check "stats reports 2 documents"      bash -c "$PY -m glean.cli stats --dir '$DEMO_DIR' | grep -q 'documents:     2'"
check "bare OR query finds a doc"      bash -c "$PY -m glean.cli search 'bloom filter' --dir '$DEMO_DIR' | grep -q raft.md"
check "AND requires both terms"        bash -c "$PY -m glean.cli search 'chess AND transposition' --dir '$DEMO_DIR' --json | python3 -c \"import json,sys; d=json.load(sys.stdin); assert [r['path'] for r in d['results']]==['chess.md'], d; print('ok')\""
check "AND excludes non-matching doc"  bash -c "$PY -m glean.cli search 'chess AND bloom' --dir '$DEMO_DIR' --json | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['results']==[], d\""
check "phrase query requires adjacency" bash -c "$PY -m glean.cli search '\"alpha-beta search\"' --dir '$DEMO_DIR' --json | python3 -c \"import json,sys; d=json.load(sys.stdin); assert [r['path'] for r in d['results']]==['chess.md'], d\""
check "NOT excludes matching doc"      bash -c "$PY -m glean.cli search 'NOT chess' --dir '$DEMO_DIR' --json | python3 -c \"import json,sys; d=json.load(sys.stdin); assert [r['path'] for r in d['results']]==['raft.md'], d\""
check "fuzzy typo correction works"    bash -c "$PY -m glean.cli search 'consesus' --dir '$DEMO_DIR' --json | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['results'] and d['results'][0]['path']=='raft.md', d; assert d['suggestions'], d\""
check "incremental reindex reuses files" bash -c "$PY -m glean.cli index '$DEMO_DIR' | grep -q '2 unchanged/reused'"
echo

echo "== 3. HTTP server + API smoke test =="
PORT=8934
$PY -m glean.cli serve --dir "$DEMO_DIR" --port "$PORT" >/tmp/glean_demo_server.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$DEMO_DIR"' EXIT
sleep 1
check "server responds on /"           bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/)\" = 200 ]"
check "server /api/stats returns json" bash -c "curl -s http://127.0.0.1:$PORT/api/stats | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['documents']==2, d\""
check "server /api/search returns highlighted snippet" bash -c "curl -s 'http://127.0.0.1:$PORT/api/search?q=bloom+filter' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert '<mark>' in d['results'][0]['snippet'], d\""
check "server handles empty query gracefully" bash -c "curl -s 'http://127.0.0.1:$PORT/api/search?q=' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['results']==[]\""
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
trap - EXIT
rm -rf "$DEMO_DIR"
echo

echo "== 4. Self-indexing demo over this repo's own history =="
$PY -m glean.cli demo
echo

if [ "$FAILED" -ne 0 ]; then
  echo "DEMO FAILED — see PASS/FAIL lines above."
  exit 1
fi
echo "All checks passed."
