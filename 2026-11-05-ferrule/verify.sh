#!/usr/bin/env bash
# Full verification: unit/integration/differential tests, hostile-input battery, larger fuzz, demo.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
echo "[1/4] unittest suite";            python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py'
echo "[2/4] hostile-input battery";     python3 tests/attack_battery.py | awk '/BAD/{bad++} END{print (bad?bad:0) " crashes"; exit bad?1:0}'
echo "[3/4] larger assembler fuzz"
out="$(python3 tests/fuzz_asm.py 1500 31337)"; echo "$out"
for k in mismatch ferrule_rejects_valid accepts_invalid; do grep -q "'$k': 0" <<<"$out" || { echo "fuzz: $k != 0"; exit 1; }; done
grep -q "branch programs mismatching: 0" <<<"$out"
echo "[4/4] demo";                      ./demo.sh > /dev/null && echo "demo ok"
echo "ALL GREEN"
