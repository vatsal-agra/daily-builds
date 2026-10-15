#!/usr/bin/env bash
# Rebuild the WebAssembly core used by the browser player.
set -euo pipefail
cd "$(dirname "$0")/.."
GOOS=js GOARCH=wasm go build -ldflags="-s -w" -o web/dotmatrix.wasm ./cmd/wasm
cp "$(go env GOROOT)/lib/wasm/wasm_exec.js" web/wasm_exec.js
gzip -9 -n -c web/dotmatrix.wasm > web/dotmatrix.wasm.gz   # served with Content-Encoding: gzip
rm -f web/dotmatrix.wasm
ls -l web/dotmatrix.wasm.gz
