#!/usr/bin/env bash
# demo.sh — exercises every Runic feature end to end, in order.
# Run from anywhere; fails loudly (set -e) on the first broken step.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BOLD='\033[1m'; GREEN='\033[0;32m'; RESET='\033[0m'
step() { echo -e "\n${BOLD}==> $1${RESET}"; }

step "1/8  Unit test suite (lexer, parser, typecheck, interpreter, disasm, CLI, dual-oracle)"
python3 -m unittest discover -s tests -v 2>&1 | tail -5

step "2/8  Compile every demo program to real .wasm bytes"
for f in demo/*.rn; do
  python3 cli.py compile "$f" -o "/tmp/$(basename "${f%.rn}").wasm" >/dev/null
  echo "  compiled $f"
done

step "3/8  Run programs through our from-scratch interpreter"
python3 cli.py run demo/fib.rn fib 20
python3 cli.py run demo/factorial.rn factorial 10
python3 cli.py run demo/gcd.rn gcd 1071 462
python3 cli.py run demo/is_prime.rn is_prime 9973
python3 cli.py run demo/power.rn power 2 16

step "4/8  Disassemble a compiled module back to WAT-like text"
python3 cli.py disasm demo/sieve.rn | head -12
echo "  ..."

step "5/8  Generate the interactive HTML step-through visualizer"
python3 cli.py trace demo/bubble_sort.rn sort 10 -o /tmp/runic_demo_trace.html
ls -la /tmp/runic_demo_trace.html

step "6/8  Dual-oracle differential verification (our interpreter vs Node's real WebAssembly engine)"
python3 verify.py

step "7/8  assert() compiles to a real WASM trap, verified identically in both engines"
python3 cli.py run demo/assertions.rn safe_div 10 2
if python3 cli.py run demo/assertions.rn safe_div 10 0 2>/tmp/assert_err.txt; then
  echo "FAIL: expected a trap"; exit 1
else
  echo "  correctly trapped: $(cat /tmp/assert_err.txt)"
fi

step "8/8  CLI error paths are clean (no raw tracebacks)"
if python3 cli.py run demo/fib.rn fib notanumber 2>/tmp/cli_err.txt; then
  echo "FAIL: expected an error"; exit 1
fi
if grep -q Traceback /tmp/cli_err.txt; then
  echo "FAIL: raw traceback leaked to user"; exit 1
fi
echo "  clean error: $(cat /tmp/cli_err.txt)"

echo -e "\n${GREEN}${BOLD}All Runic features exercised successfully.${RESET}"
