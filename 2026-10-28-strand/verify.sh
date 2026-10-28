#!/usr/bin/env bash
# One-command verification: unit + property + CLI tests, a scripted end-to-end demo with
# assertions, the browser check of the report, and the mutation harness (pass --quick to skip it).
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

step "build (release, warnings are errors)"
RUSTFLAGS="-D warnings" cargo build --release 2>&1 | tail -2

step "tests"
cargo test --release 2>&1 | grep -E "^test result|FAILED|panicked" | sort | uniq -c

step "end-to-end demo with assertions"
OUT=$(mktemp -d)
./target/release/strand demo --o "$OUT" --length 200000 --seed 7 | tee "$OUT/demo.txt"
python3 - "$OUT/demo.txt" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
def num(pat):
    m = re.search(pat, t); assert m, "missing: " + pat; return float(m.group(1))
acc = num(r"accuracy ([\d.]+)% of mapped"); assert acc > 99.5, acc
q20 = num(r"MAPQ>=20: ([\d.]+)%\)"); assert q20 > 99.95, q20
snp = re.search(r"SNP\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)", t); assert snp
assert float(snp.group(4)) > 0.99 and float(snp.group(5)) > 0.93, snp.group(0)
gf = num(r"genome fraction ([\d.]+)%"); assert gf > 85, gf
assert "misassemblies 0" in t
print("demo assertions OK: map accuracy %.2f%%, SNP P/R %s/%s, genome fraction %.1f%%" % (acc, snp.group(4), snp.group(5), gf))
PY

step "report in a headless browser (light / dark / phone)"
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  node tools/report_check.js "$OUT/report.html"
else
  echo "(node + playwright not available: skipped)"
fi

if [ "${1:-}" != "--quick" ]; then
  step "mutation harness"
  ./tools/mutants.sh
fi
printf '\n\033[1;32mALL GREEN\033[0m\n'
