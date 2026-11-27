#!/usr/bin/env bash
# Runnable demo + verification of every Fathom feature. Exit code != 0 on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

step "1/7 unit + integration tests (engine, solver vs brute force, generator, analysis, CLI, bundle, server)"
node --test "test/*.test.js" 2>&1 | grep -E "^# (tests|pass|fail)"
node --test "test/*.test.js" >/dev/null

step "2/7 exact solver on a real mid-game position (CLI solve)"
TMP=$(mktemp -d)
node --input-type=module -e "
import { Game } from './src/board.js';
const g = new Game({ w: 9, h: 9, mines: 10, seed: 'demo' }); g.reveal(40);
let o=''; for (let y=0;y<9;y++){ for(let x=0;x<9;x++){const i=y*9+x; o+=(g.state[i]===1?(g.adj[i]||'.'):'#')+' ';} o+='\n'; }
process.stdout.write(o);" > "$TMP/board.txt"
cat "$TMP/board.txt"
node src/cli.js solve "$TMP/board.txt" --mines 10

step "3/7 no-guess generator (expert) — verified by a certain-only solver"
node src/cli.js generate --level expert --seed demo --no-guess

step "4/7 solver benchmark (win rates; intermediate/expert land near published optimal-play figures)"
node src/cli.js bench --level beginner --games 100 --seed demo
node src/cli.js bench --level intermediate --games 100 --seed demo
node src/cli.js bench --level expert --games 40 --seed demo
node src/cli.js bench --level expert --games 20 --seed demo --no-guess

step "5/7 standalone bundle"
node build.js

step "6/7 luck analyzer (scripted terminal session)"
printf 'r 5 5\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nq\n' | node src/cli.js play --level beginner --seed demo | tail -n 8

step "7/7 browser end-to-end (needs Playwright; skipped if unavailable)"
if node -e "require('playwright')" 2>/dev/null || NODE_PATH="$(npm root -g 2>/dev/null)" node -e "require('playwright')" 2>/dev/null; then
  NODE_PATH="$(npm root -g 2>/dev/null)" node test/ui.e2e.cjs
else
  echo "Playwright not installed — skipping UI e2e (npm i -g playwright to enable)"
fi
printf '\n\033[1;32mAll Fathom checks passed.\033[0m\n'
