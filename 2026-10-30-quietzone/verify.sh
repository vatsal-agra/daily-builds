#!/usr/bin/env bash
# One command that proves the whole project: format, vet, unit/fuzz/differential
# tests, benchmark floors, CLI demo, cross-check against OpenCV + segno, and
# the mutation harness.
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n== %s\n' "$*"; }
step "gofmt";  test -z "$(gofmt -l .)" || { gofmt -l .; echo "gofmt drift"; exit 1; }
step "go vet"; go vet ./...
step "go test"; go test -count=1 ./...
step "benchmark floors (36 trials/scenario)"; go build -o /tmp/qz-verify ./cmd/qz && /tmp/qz-verify bench -n 36 -strict
step "CLI demo";  ./demo.sh
if command -v python3.13 >/dev/null && python3.13 -c "import segno,cv2" 2>/dev/null; then
  step "cross-check vs OpenCV and segno"; python3.13 tools/crosscheck.py /tmp/qz-verify 40 2>&1 | grep -v WARN
else echo "(skipping cross-check: python3.13 with segno+opencv not installed)"; fi
if [ "${1:-}" = "--mutate" ]; then step "mutation harness"; tools/mutate.sh; fi
printf '\nALL GREEN\n'
