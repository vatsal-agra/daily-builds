#!/usr/bin/env bash
# Zugzwang demo/verification script -- exercises every feature described
# in PLAN.md and README.md in one run, printing evidence for each, and
# exits non-zero if anything fails.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
step() { echo; echo "=== $1 ==="; }
ok()   { PASS=$((PASS+1)); echo "  [PASS] $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }

step "1/6  Unit test suite (move gen, search, eval, PGN, book, server -- 56 tests)"
if python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tee /tmp/zugzwang_demo_tests.log | tail -5; then
  if grep -q "^OK" /tmp/zugzwang_demo_tests.log; then ok "unittest suite"; else bad "unittest suite"; fi
else
  bad "unittest suite (non-zero exit)"
fi

step "2/6  Perft verification (required feature 1: legal move generation)"
if python3 -m zugzwang.cli perft --depth 4 | tee /tmp/zugzwang_demo_perft.log; then
  if grep -q "depth 4: 197281 nodes" /tmp/zugzwang_demo_perft.log; then
    ok "perft depth 4 == 197281 (published reference value)"
  else
    bad "perft depth 4 node count mismatch"
  fi
else
  bad "perft command failed"
fi

step "3/6  Engine-vs-engine self-play with opening book, then out-of-book search (required features 2, 3; stretch 7)"
if python3 -m zugzwang.cli selfplay --time 0.5 --max-moves 12 --ascii --pgn /tmp/zugzwang_demo_game.pgn | tee /tmp/zugzwang_demo_selfplay.log; then
  if grep -q "book" /tmp/zugzwang_demo_selfplay.log && grep -qE "depth [0-9]+" /tmp/zugzwang_demo_selfplay.log; then
    ok "selfplay used both the opening book and out-of-book search"
  else
    bad "selfplay did not show expected book+search mix"
  fi
else
  bad "selfplay command failed"
fi

step "4/6  PGN export/replay round trip (stretch feature 6)"
if [ -s /tmp/zugzwang_demo_game.pgn ]; then
  cat /tmp/zugzwang_demo_game.pgn
  ok "PGN file written"
  if python3 -c "
from zugzwang.pgn import replay_pgn
with open('/tmp/zugzwang_demo_game.pgn') as f:
    board, hist, hashes = replay_pgn(f.read())
print(f'replayed {len(hist)} moves back to final FEN: {board.to_fen()}')
"; then
    ok "PGN replayed back to a consistent final position"
  else
    bad "PGN replay failed"
  fi
else
  bad "no PGN file was produced"
fi

step "5/6  Transposition table + Zobrist hashing sanity (stretch feature 5)"
if python3 -c "
from zugzwang.board import Board, START_FEN
from zugzwang.search import Searcher
s = Searcher()
b = Board.from_fen(START_FEN)
move, score, depth = s.choose_move(b, seconds=1.0)
assert len(s.tt.table) > 0, 'transposition table is empty after a real search'
print(f'TT has {len(s.tt.table)} entries after a depth-{depth} search ({s.nodes} nodes)')
"; then
  ok "transposition table populated during search"
else
  bad "transposition table check failed"
fi

step "6/6  Web server + JSON API smoke test (required feature 4: playable web UI)"
python3 -m zugzwang.server --port 8799 --think-time 0.3 > /tmp/zugzwang_demo_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1
if curl -s -f http://127.0.0.1:8799/ -o /tmp/zugzwang_demo_index.html; then
  ok "index page served"
else
  bad "index page did not serve"
fi
STATE=$(curl -s -X POST http://127.0.0.1:8799/api/move -H "Content-Type: application/json" -d '{"uci":"e2e4"}')
echo "  POST /api/move e2e4 -> $STATE" | head -c 300; echo
if echo "$STATE" | grep -q '"to_move": "black"'; then
  ok "web API applied a move and advanced the turn"
else
  bad "web API move did not advance turn as expected"
fi
ENGINE_STATE=$(curl -s -X POST http://127.0.0.1:8799/api/engine_move -H "Content-Type: application/json" -d '{}')
echo "  POST /api/engine_move -> $ENGINE_STATE" | head -c 300; echo
if echo "$ENGINE_STATE" | grep -q '"to_move": "white"'; then
  ok "engine replied via the real API (not a mock)"
else
  bad "engine_move did not produce the expected reply"
fi
kill $SERVER_PID 2>/dev/null
trap - EXIT

echo
echo "=================================================="
echo "  RESULT: $PASS passed, $FAIL failed"
echo "=================================================="
[ "$FAIL" -eq 0 ]
