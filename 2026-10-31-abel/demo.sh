#!/usr/bin/env bash
# Verification: static checks, the full Go test-suite, a golden-file run of the demo script that exercises
# every feature, and the adversarial-review battery (which must never hit an internal error).
set -euo pipefail
cd "$(dirname "$0")"
bin="$(mktemp -d)/abel"

echo "== go vet"; go vet ./...
echo "== go test"; go test ./... 2>&1
echo "== build"; go build -o "$bin" ./cmd/abel

echo "== demo script vs golden output (testdata/demo.expected)"
out="$(mktemp)"
"$bin" -f testdata/demo.abel > "$out" 2>&1 || true   # deliberate error lines make the script exit 1
diff -u testdata/demo.expected "$out" && echo "golden output matches"

echo "== certificates issued by the demo"
echo "integrals certified : $(grep -c '✓ certified: d/dx' "$out")"
echo "factorisations      : $(grep -c '✓ certified: expanding' "$out")"
echo "honest refusals     : $(grep -c '^error:' "$out")"

echo "== adversarial battery (no internal errors allowed)"
bad=$("$bin" -f testdata/review_attack.txt 2>&1 | grep -c 'internal error' || true)
[ "$bad" = "0" ] && echo "0 internal errors over $(grep -vc '^$' testdata/review_attack.txt) hostile inputs"

echo "== one-shot mode"
"$bin" -e 'integrate(x*sin(x), x)'
echo "ALL GREEN"
