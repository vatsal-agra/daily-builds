#!/usr/bin/env bash
# Full verification: unit/integration/fuzz/oracle tests, the CLI demo, and headless-browser checks
# of the HTML renderer and the cast player. Exit status is non-zero on any failure.
set -u
cd "$(dirname "$0")"
fail=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "cargo test (all suites: parser, screen, sgr/render, pty, tmux oracle, fuzz, cast, reflow, input)"
cargo test 2>&1 | tee /tmp/cathode-test.log | grep -E "^(test result|test .*FAILED|failures:)" || true
grep -q "FAILED\|failures:" /tmp/cathode-test.log && fail=1
total=$(grep -E "^test result" /tmp/cathode-test.log | sed -E 's/.* ([0-9]+) passed.*/\1/' | paste -sd+ | bc)
echo "  total tests passed: $total"

step "demo.sh (CLI end to end)"
./demo.sh | grep -E "FAIL|Demo:" ; [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

step "headless Chromium: HTML renderer + cast player"
PW=${PLAYWRIGHT_MODULE:-$(readlink -f "$(npm root -g 2>/dev/null)/playwright" 2>/dev/null)}
if [ -n "$PW" ] && [ -d "$PW" ] && ls /opt/pw-browsers/chromium* >/dev/null 2>&1; then
  export PLAYWRIGHT_MODULE=$PW
  node tools/shot.js out/ls.html out/ls.png dark --info && node tools/shot.js out/ls.html out/ls-light.png light
  res=$(node tools/check_player.js out/player.html out/player.png) && echo "  player: $res" && grep -q '"errors":\[\]' <<<"$res" || fail=1
else
  echo "  (Playwright/Chromium not available: skipped)"
fi

echo
if [ $fail -eq 0 ]; then printf '\033[32mVERIFY OK\033[0m\n'; else printf '\033[31mVERIFY FAILED\033[0m\n'; fi
exit $fail
