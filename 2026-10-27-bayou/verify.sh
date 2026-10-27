#!/usr/bin/env bash
# Full verification: formatting, vet, every Go test, the CLI demo (incl. headless-browser check),
# and a mutation run proving the tests notice injected bugs. usage: ./verify.sh [--quick]
set -euo pipefail
cd "$(dirname "$0")"
quick=${1:-}
echo "== gofmt";  test -z "$(gofmt -l .)" || { gofmt -l .; echo "files need gofmt"; exit 1; }
echo "== go vet"; go vet ./...
echo "== go test (all packages, uncached)"; go test -count=1 ./...
echo "== demo (every feature through the CLI)"; ./demo.sh | tail -3
if [ "$quick" != "--quick" ]; then echo "== mutation check"; tests/mutation.sh; fi
echo; echo "ALL GREEN"
