#!/usr/bin/env bash
# Full verification: formatting, vet, unit/fuzz/differential tests, then the end-to-end CLI demo.
set -e
cd "$(dirname "$0")"
echo "== gofmt"; test -z "$(gofmt -l .)" || { gofmt -l .; echo "files need gofmt"; exit 1; }
echo "== go vet"; go vet ./...
echo "== go test (count=1)"; go test -count=1 ./...
echo "== demo"; ./demo.sh
echo; echo "ALL GREEN"
