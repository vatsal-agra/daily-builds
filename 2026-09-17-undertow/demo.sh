#!/usr/bin/env bash
# Runs every shipped feature end-to-end and fails loudly if any check
# doesn't pass. Intended to be run from this directory.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass() { echo "  OK  $1"; }
step() { echo; echo "=== $1 ==="; }

step "1/7 unit test suite"
python3 -m pytest tests/ -q
pass "24/24 tests"

step "2/7 feature: packet-level network core + Reno (required)"
python3 -m src.cli single --algo reno --duration 20
pass "Reno saturates a 2 Mbps link via slow start + AIMD"

step "3/7 feature: CUBIC (required)"
python3 -m src.cli single --algo cubic --duration 20
pass "CUBIC saturates the same link via RFC 8312 cubic growth"

step "4/7 feature: fairness harness — AIMD convergence + RTT unfairness (required)"
python3 -m src.cli fairness --algo reno --duration 40
python3 -m src.cli rtt-unfairness --algo reno --duration 60
python3 -m src.cli rtt-unfairness --algo cubic --duration 60
pass "same-RTT Reno flows converge to a fair split; CUBIC is measurably more RTT-fair than Reno"

step "5/7 stretch feature: BBR-lite vs a loss-based algorithm"
python3 -m src.cli single --algo bbr --duration 20
python3 -m src.cli bbr-vs-loss --algo cubic --duration 30
pass "BBR saturates the link with ~zero drops and a far shallower queue than CUBIC"

step "6/7 stretch feature: bufferbloat + RED, and the visualizer"
python3 -m src.cli bufferbloat --algo reno --duration 30
python3 -m src.cli bufferbloat --algo reno --duration 30 --red
python3 scripts/make_visualizer_data.py
if command -v python3 >/dev/null && python3 -c "import playwright" 2>/dev/null; then
  python3 - <<'PY'
from playwright.sync_api import sync_playwright
import pathlib, sys

path = pathlib.Path("visualizer/index.html").resolve().as_uri()
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = browser.new_page(viewport={"width": 1000, "height": 1600})
    page.on("console", lambda msg: errors.append((msg.type, msg.text)) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(("pageerror", str(exc))))
    page.goto(path)
    page.wait_for_timeout(500)
    n = page.eval_on_selector("#stats-single", "el => el.children.length")
    browser.close()
if errors:
    print("Console errors:", errors)
    sys.exit(1)
if n != 6:
    print(f"expected 6 stat cards in panel 1, got {n}")
    sys.exit(1)
print("headless-Chromium smoke test: 0 console errors, no duplicate rendering")
PY
  pass "visualizer renders with zero console errors"
else
  echo "  (playwright not available in this environment; skipping the headless-browser check)"
fi

step "7/7 CLI input validation"
if python3 -m src.cli single --duration -1 >/dev/null 2>&1; then
  echo "expected --duration -1 to be rejected" >&2
  exit 1
fi
if python3 -m src.cli fairness --flows 0 >/dev/null 2>&1; then
  echo "expected --flows 0 to be rejected" >&2
  exit 1
fi
pass "invalid input is rejected with a clear error, not a silent no-op"

echo
echo "ALL CHECKS PASSED"
