#!/usr/bin/env bash
# Cascade end-to-end demo: installs dev-only deps, runs the automated test
# suite (unit + dnspython differential oracle + live-socket + CLI subprocess
# tests), then runs the scripted `cascade demo` feature walkthrough, then
# regenerates the checked-in example HTML visualizer. Exits non-zero on any
# failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Installing dev-only dependencies (pytest, dnspython) ==="
python3 -m pip install --quiet -r requirements-dev.txt

echo
echo "=== Running the automated test suite ==="
python3 -m pytest -q

echo
echo "=== Running the full feature walkthrough (cascade demo) ==="
python3 -m cascade.cli demo

echo
echo "=== Regenerating the checked-in example resolution-trace visualizer ==="
python3 -m cascade.cli resolve www.example.com A --viz visualizer/example-trace.html --trace

echo
echo "=== All green. ==="
