#!/usr/bin/env bash
# Exercises every Kiln feature end-to-end: unit tests, the full CLI
# surface (assemble/compile/run/disasm/verify/trace), the WASI-lite host
# import demo, and the HTML visualizer. Fails loudly (set -e) on the
# first broken thing.
set -euo pipefail
cd "$(dirname "$0")"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

section() { echo; echo "=== $1 ==="; }

section "1/7  Unit test suite"
python3 -m unittest discover -s . -t . -p 'test_*.py'

section "2/7  .kwat assembler -> run -> disasm"
python3 -m kiln.cli assemble examples/hello_wasi.kwat -o "$WORKDIR/hello.wasm"
python3 -m kiln.cli disasm "$WORKDIR/hello.wasm" | head -5
OUT="$(python3 -m kiln.cli run "$WORKDIR/hello.wasm" main)"
echo "$OUT"
echo "$OUT" | grep -q "Hello from Kiln!" || { echo "FAIL: missing WASI-lite output"; exit 1; }

section "3/7  Pebble compiler -> run (recursion, loops, short-circuit)"
python3 -m kiln.cli compile examples/fib.pebble -o "$WORKDIR/fib.wasm"
FIB_OUT="$(python3 -m kiln.cli run "$WORKDIR/fib.wasm" fib 10)"
[ "$FIB_OUT" = "55" ] || { echo "FAIL: fib(10) expected 55, got $FIB_OUT"; exit 1; }
echo "fib(10) = $FIB_OUT  (correct)"

python3 -m kiln.cli compile examples/collatz.pebble -o "$WORKDIR/collatz.wasm"
COLLATZ_OUT="$(python3 -m kiln.cli run "$WORKDIR/collatz.wasm" collatz_steps 27)"
[ "$COLLATZ_OUT" = "111" ] || { echo "FAIL: collatz_steps(27) expected 111, got $COLLATZ_OUT"; exit 1; }
echo "collatz_steps(27) = $COLLATZ_OUT  (correct)"

section "4/7  Differential verification against Node's real WASM engine"
if command -v node >/dev/null 2>&1; then
  python3 -m kiln.cli verify "$WORKDIR/fib.wasm" fib 10
  python3 -m kiln.cli verify "$WORKDIR/hello.wasm" main
else
  echo "node not on PATH -- skipping (unit tests already skip the node-diff suite in this case)"
fi

section "5/7  Interactive HTML trace visualizer"
python3 -m kiln.cli trace "$WORKDIR/fib.wasm" fib 6 --html -o "$WORKDIR/trace.html"
python3 - "$WORKDIR/trace.html" <<'PYEOF'
import re, sys, json
html = open(sys.argv[1]).read()
m = re.search(r"const EMBEDDED_TRACE = (.*);", html)
assert m, "trace HTML missing embedded JSON"
data = json.loads(m.group(1))
assert data["result"] == [8], f"expected fib(6)=8, got {data['result']}"
assert len(data["steps"]) > 0
print(f"embedded trace OK: {len(data['steps'])} steps, result={data['result']}")
PYEOF

section "6/7  CLI error handling on bad input (must NOT show a traceback)"
if python3 -m kiln.cli run "$WORKDIR/nope.wasm" main 2>"$WORKDIR/err.txt"; then
  echo "FAIL: expected nonzero exit for a missing file"; exit 1
fi
grep -q "Traceback" "$WORKDIR/err.txt" && { echo "FAIL: raw traceback leaked to the user"; exit 1; }
grep -q "kiln run:" "$WORKDIR/err.txt" || { echo "FAIL: no clean error message"; exit 1; }
echo "clean error: $(cat "$WORKDIR/err.txt")"

section "7/7  Round-trip fidelity: assemble -> decode -> re-encode is byte-identical"
python3 - "$WORKDIR/fib.wasm" <<'PYEOF'
import sys
sys.path.insert(0, ".")
from kiln.wasm.decoder import decode_module
from kiln.wasm.encoder import encode_module
data = open(sys.argv[1], "rb").read()
assert encode_module(decode_module(data)) == data, "round-trip mismatch"
print("byte-for-byte round-trip OK")
PYEOF

echo
echo "=== All checks passed ==="
