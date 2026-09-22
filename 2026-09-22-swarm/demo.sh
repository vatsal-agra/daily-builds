#!/usr/bin/env bash
# Full verification pass for Swarm: unit suite, the flagship multi-process
# demo (both scenarios), a manual CLI walkthrough (make-torrent -> tracker
# -> seed -> leech, driven as separate real processes, not the demo module),
# and a headless-Chromium pass over the live dashboard. Exits non-zero on
# the first failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=python3
PASS="\033[32mPASS\033[0m"
FAIL="\033[31mFAIL\033[0m"
step() { echo; echo "== $1 =="; }

step "1/4 unit test suite"
$PY -m unittest discover -s tests
echo -e "$PASS unit suite"

step "2/4 flagship end-to-end demo (real tracker + real multi-process swarm, 2 scenarios)"
$PY -m swarm.cli demo
echo -e "$PASS swarm demo"

step "3/4 manual CLI walkthrough: make-torrent -> tracker -> seed -> leech as independent processes"
WORK=$(mktemp -d)
trap 'kill $TRACKER_PID $SEED_PID >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

$PY -c "
import random
r = random.Random(99)
with open('$WORK/payload.bin', 'wb') as f:
    f.write(r.randbytes(150 * 1024))
"

$PY -m swarm.cli tracker --host 127.0.0.1 --port 0 > "$WORK/tracker.log" 2>&1 &
TRACKER_PID=$!
sleep 0.5
TRACKER_PORT=$(grep -oE ':[0-9]+/announce' "$WORK/tracker.log" | head -1 | tr -d ':/announce')
if [ -z "$TRACKER_PORT" ]; then
  echo -e "$FAIL tracker did not report its port"; cat "$WORK/tracker.log"; exit 1
fi
TRACKER_URL="http://127.0.0.1:${TRACKER_PORT}/announce"
echo "tracker: $TRACKER_URL"

$PY -m swarm.cli make-torrent "$WORK/payload.bin" --announce "$TRACKER_URL" -o "$WORK/payload.torrent" --piece-length 16384
test -f "$WORK/payload.torrent"
echo -e "$PASS make-torrent produced a .torrent file"

$PY -m swarm.cli seed "$WORK/payload.torrent" "$WORK/payload.bin" --port 0 > "$WORK/seed.log" 2>&1 &
SEED_PID=$!
sleep 0.5

$PY -m swarm.cli leech "$WORK/payload.torrent" --out "$WORK/payload.copy.bin" --timeout 30 --status-file "$WORK/leech-status.json" > "$WORK/leech.log" 2>&1
if ! cmp -s "$WORK/payload.bin" "$WORK/payload.copy.bin"; then
  echo -e "$FAIL leeched file does not match the original byte-for-byte"
  cat "$WORK/leech.log"
  exit 1
fi
echo -e "$PASS leech reconstructed the file byte-for-byte over the real CLI (tracker/seed/leech as separate processes)"

kill $SEED_PID $TRACKER_PID >/dev/null 2>&1 || true
wait $SEED_PID $TRACKER_PID 2>/dev/null || true

step "3b/4 CLI error handling on bad input (should be clean, no tracebacks)"
if $PY -m swarm.cli make-torrent /nonexistent/file.bin --announce http://x/announce 2>"$WORK/err.txt"; then
  echo -e "$FAIL expected make-torrent on a missing file to fail"; exit 1
fi
if grep -q Traceback "$WORK/err.txt"; then
  echo -e "$FAIL raw traceback leaked to the user"; cat "$WORK/err.txt"; exit 1
fi
grep -q "^error:" "$WORK/err.txt"
echo -e "$PASS bad input produces a clean error, not a traceback"

step "4/4 headless-Chromium pass over the live dashboard"
if command -v node >/dev/null 2>&1 && [ -d /opt/node22/lib/node_modules/playwright ] && [ -d /opt/pw-browsers ]; then
  NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    node tests/dashboard_browser_test.cjs
  echo -e "$PASS dashboard renders live in headless Chromium, zero console errors"
else
  echo "(skipped: node/playwright/chromium not found in this environment)"
fi

echo
echo -e "$PASS all demo.sh checks passed"
