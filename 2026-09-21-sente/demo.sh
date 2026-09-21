#!/usr/bin/env bash
# Sente demo.sh -- exercises every shipped feature end-to-end and prints
# a pass/fail summary. Uses the checkpoints already committed to this
# repo for the oracle/tournament/server steps (so it doesn't have to
# retrain from scratch every run), but ALSO runs a short, real, from-
# scratch training loop in a scratch directory to prove the self-play +
# training pipeline itself genuinely runs end-to-end, not just that
# pre-baked checkpoints exist.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
FAILED_STEPS=()

step() {
  local name="$1"; shift
  echo
  echo "==> $name"
  if "$@"; then
    echo "PASS: $name"
    PASS=$((PASS+1))
  else
    echo "FAIL: $name"
    FAIL=$((FAIL+1))
    FAILED_STEPS+=("$name")
  fi
}

echo "Sente demo.sh -- exercising every feature"
echo "=========================================="

# 1. Gradient checks (required feature #2: from-scratch backprop, checked)
step "1. Gradient checks (finite differences vs hand-derived backward)" \
  python3 scripts/run_gradcheck.py

# 2. A short, REAL, from-scratch self-play training run (required feature
#    #3), in a scratch checkpoint dir so it never touches the committed
#    checkpoints used by the rest of this demo.
SCRATCH_CKPT_DIR="$(mktemp -d)"
step "2. Self-play + training loop, from-scratch, end-to-end (short run)" \
  env SENTE_GENERATIONS=3 SENTE_GAMES_PER_GEN=10 SENTE_SIMS=30 \
  python3 -c "
import sys, os
sys.path.insert(0, '.')
from sente.games.tictactoe import TicTacToe
from sente.train import TrainConfig, run_training
config = TrainConfig(n_generations=3, games_per_generation=10, n_simulations=30,
                      hidden_sizes=(32,32), buffer_size=2000, batch_size=32,
                      train_steps_per_generation=50, checkpoint_dir='$SCRATCH_CKPT_DIR')
net, history, ckpts = run_training(TicTacToe, config)
assert len(ckpts) == 4, f'expected 4 checkpoints (gen0..gen3), got {len(ckpts)}'
assert history[-1]['losses']['total'] < history[0]['losses']['total'], 'loss did not decrease at all'
print(f\"OK: loss {history[0]['losses']['total']:.3f} -> {history[-1]['losses']['total']:.3f} over {len(history)} generations, {len(ckpts)} checkpoints saved\")
"
rm -rf "$SCRATCH_CKPT_DIR"

# 3. Full unit test suite (covers games, MCTS sign conventions, Dirichlet-
#    noise-leak regressions, and the server API against real HTTP calls).
step "3. Unit test suite" \
  python3 -m unittest discover -s tests -v

# 4. Ground-truth minimax-oracle invariant (required feature #4a), against
#    the fully-trained committed Tic-Tac-Toe checkpoint.
TTT_CKPT="checkpoints/tictactoe/tictactoe_gen025.npz"
if [ -f "$TTT_CKPT" ]; then
  step "4. Minimax-oracle 'never loses to perfect play' check" \
    env SENTE_ORACLE_SIMS=80 python3 scripts/run_oracle_check.py "$TTT_CKPT"
else
  echo "SKIP: 4. oracle check ($TTT_CKPT not found -- run scripts/run_training_ttt.py first)"
fi

# 5. Cross-generation win-rate / Elo report (required feature #4b).
# Uses fewer games/sims than the full report quoted in README.md purely
# to keep demo.sh fast, and writes to a scratch path (NOT
# reports/tournament_tictactoe.json) so it never overwrites the
# authoritative, larger-sample numbers actually quoted in README.md.
if [ -d "checkpoints/tictactoe" ]; then
  step "5. Cross-generation Tic-Tac-Toe win-rate / Elo report" \
    env SENTE_TOURNEY_GAMES=10 SENTE_TOURNEY_SIMS=40 SENTE_REPORT_PATH="$(mktemp -u).json" python3 scripts/run_tournament.py
else
  echo "SKIP: 5. tournament (no tictactoe checkpoints found)"
fi

# 6. Connect Four Jr stretch feature: cross-generation report + wide-
#    margin baselines. Same "scratch report path, smaller sample" note
#    as step 5 above -- README.md's numbers come from the full run
#    committed in reports/tournament_connect4jr.json.
if [ -d "checkpoints/connect4jr" ]; then
  step "6. Connect Four Jr stretch: cross-generation report + baselines" \
    env SENTE_TOURNEY_GAMES=6 SENTE_TOURNEY_SIMS=40 SENTE_REPORT_PATH="$(mktemp -u).json" python3 scripts/run_tournament_c4.py
else
  echo "SKIP: 6. Connect Four Jr tournament (no checkpoints found -- run scripts/run_training_c4.py first)"
fi

# 7. Server-backed UI stretch feature: start the real server, verify it
#    with a headless-Chromium smoke test (zero console errors), stop it.
if [ -f "checkpoints/tictactoe/tictactoe_gen000.npz" ] && command -v node >/dev/null 2>&1; then
  echo
  echo "==> 7. Server + headless-Chromium UI smoke test"
  PORT=8799
  python3 scripts/run_server.py "$PORT" > /tmp/sente_demo_server.log 2>&1 &
  SERVER_PID=$!
  sleep 1.5
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/health" | grep -q 200; then
    NODE_PATH="$(node -e 'console.log(require("path").dirname(require.resolve("playwright/package.json")))' 2>/dev/null | xargs dirname 2>/dev/null || echo /opt/node22/lib/node_modules)"
    if [ -z "$NODE_PATH" ] || [ ! -d "$NODE_PATH" ]; then NODE_PATH=/opt/node22/lib/node_modules; fi
    if NODE_PATH="$NODE_PATH" node scripts/playwright_smoke.js "http://127.0.0.1:$PORT"; then
      echo "PASS: 7. Server + headless-Chromium UI smoke test"
      PASS=$((PASS+1))
    else
      echo "FAIL: 7. Server + headless-Chromium UI smoke test"
      FAIL=$((FAIL+1))
      FAILED_STEPS+=("7. Server + headless-Chromium UI smoke test")
    fi
  else
    echo "FAIL: 7. server did not come up on port $PORT (see /tmp/sente_demo_server.log)"
    FAIL=$((FAIL+1))
    FAILED_STEPS+=("7. Server + headless-Chromium UI smoke test")
  fi
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
else
  echo "SKIP: 7. server/UI smoke test (missing checkpoint or node)"
fi

echo
echo "=========================================="
echo "Sente demo.sh summary: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  echo "Failed steps:"
  for s in "${FAILED_STEPS[@]}"; do echo "  - $s"; done
  exit 1
fi
echo "ALL CHECKS GREEN."
exit 0
